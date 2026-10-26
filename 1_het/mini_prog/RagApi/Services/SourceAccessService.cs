using System.Diagnostics;
using System.Text;
using System.Text.RegularExpressions;
using ef;
using Microsoft.EntityFrameworkCore;

public enum SourceLookupStatus { Found, ProjectNotFound, Forbidden, FileNotFound, ObjectMissing, Invalid }

public record SourceLookup<T>(SourceLookupStatus Status, T? Data = default, string? Error = null);

public record SourceFilesRequest(int userId, int investigationId, bool includeFiles = false);
public record SourceContentRequest(int userId, int investigationId, string path, int? startLine = null, int? endLine = null, int? maxLines = null);
public record SourceSearchRequest(int userId, int investigationId, string pattern, bool isRegex = false, string? pathGlob = null, List<string>? extensions = null, int? maxResults = null);

public record SourceFileDto(string Path, long Size, string Extension);
public record SourceFilesResponse(string? CommitSha, string FileSetHash, int FileCount, List<SourceFileDto>? Files);
public record SourceContentResponse(string Path, int TotalLines, int StartLine, int EndLine, List<string> Lines, bool Truncated);
public record SourceMatchDto(string Path, int Line, string Text);
public record SourceSearchResponse(List<SourceMatchDto> Matches, bool Truncated, int FilesSearched);

public class SourceAccessService
{
    public const int MaxLines = 400;
    public const int MaxFileBytes = 2 * 1024 * 1024;
    public const int MaxSearchFiles = 500;
    public const int MaxSearchResults = 50;
    public const int MaxLineText = 300;
    public static readonly TimeSpan RegexTimeout = TimeSpan.FromMilliseconds(200);
    public static readonly TimeSpan SearchBudget = TimeSpan.FromSeconds(10);

    private readonly CodeDbContext db;
    private readonly MinioService minio;

    public SourceAccessService(CodeDbContext context, MinioService minioService)
    {
        db = context;
        minio = minioService;
    }

    private record ProjectAccess(int OwnerId, int InvestigationId);

    private async Task<(SourceLookupStatus Status, ProjectAccess? Access)> AuthorizeAsync(int projectId, int userId, int investigationId)
    {
        var project = await db.Projects
            .Where(p => p.ID == projectId)
            .Select(p => new { p.InvestigationID, OwnerId = p.Investigation.UserID })
            .FirstOrDefaultAsync();

        if (project == null) return (SourceLookupStatus.ProjectNotFound, null);
        if (project.OwnerId != userId || project.InvestigationID != investigationId) return (SourceLookupStatus.Forbidden, null);
        return (SourceLookupStatus.Found, new ProjectAccess(project.OwnerId, project.InvestigationID));
    }

    public static string? SafeRelativePath(string? path)
    {
        if (string.IsNullOrWhiteSpace(path) || path.Contains('\0')) return null;
        var trimmed = path.Trim();
        if (Path.IsPathRooted(trimmed) || trimmed.StartsWith("~") || Regex.IsMatch(trimmed, "^[A-Za-z]:")) return null;
        var normalized = EvidenceJson.NormalizePath(trimmed);
        while (normalized.StartsWith("./")) normalized = normalized[2..];
        var segments = normalized.Split('/');
        if (segments.Any(s => s is "" or "." or "..")) return null;
        return normalized;
    }

    public async Task<SourceLookup<SourceFilesResponse>> FilesAsync(int projectId, SourceFilesRequest request)
    {
        var (status, _) = await AuthorizeAsync(projectId, request.userId, request.investigationId);
        if (status != SourceLookupStatus.Found) return new(status);

        var files = await db.Files.Where(f => f.ProjectID == projectId).ToListAsync();
        var codeFiles = MetricsAnalysisService.CodeFilesOf(files);
        var commitSha = await db.Repositories
            .Where(r => r.ProjectID == projectId && r.Status == RepositoryStatus.Ready)
            .OrderByDescending(r => r.IndexedAt)
            .Select(r => r.CommitSha)
            .FirstOrDefaultAsync();

        var listing = request.includeFiles
            ? files.Select(f => new SourceFileDto(EvidenceJson.NormalizePath(f.RelativePath), f.Size, f.Extension)).ToList()
            : null;

        return new(SourceLookupStatus.Found, new SourceFilesResponse(
            string.IsNullOrEmpty(commitSha) ? null : commitSha,
            MetricsAnalysisService.FileSetHash(codeFiles),
            files.Count,
            listing));
    }

    private async Task<DbFile?> FindFileAsync(int projectId, string path)
    {
        var candidates = await db.Files.Where(f => f.ProjectID == projectId).ToListAsync();
        return candidates
            .Where(f => EvidenceJson.NormalizePath(f.RelativePath) == path)
            .OrderBy(f => f.ID)
            .FirstOrDefault();
    }

    private async Task<string?> ReadTextAsync(ProjectAccess access, int projectId, DbFile file)
    {
        var bytes = await minio.ReadObjectAsync(MinioService.ObjectName(access.OwnerId, access.InvestigationId, projectId, file.RelativePath));
        if (bytes == null) return null;
        if (bytes.Length > MaxFileBytes) bytes = bytes[..MaxFileBytes];
        if (Array.IndexOf(bytes, (byte)0, 0, Math.Min(bytes.Length, 8000)) >= 0) return "";
        using var reader = new StreamReader(new MemoryStream(bytes), Encoding.UTF8, detectEncodingFromByteOrderMarks: true);
        return await reader.ReadToEndAsync();
    }

    private static List<string> SplitLines(string text) =>
        text.Split('\n').Select(l => l.TrimEnd('\r')).ToList();

    public async Task<SourceLookup<SourceContentResponse>> ContentAsync(int projectId, SourceContentRequest request)
    {
        var (status, access) = await AuthorizeAsync(projectId, request.userId, request.investigationId);
        if (status != SourceLookupStatus.Found) return new(status);

        var path = SafeRelativePath(request.path);
        if (path == null) return new(SourceLookupStatus.Invalid, Error: "path must be repository-relative");

        var file = await FindFileAsync(projectId, path);
        if (file == null) return new(SourceLookupStatus.FileNotFound, Error: "file not found in this project");

        var text = await ReadTextAsync(access!, projectId, file);
        if (text == null) return new(SourceLookupStatus.ObjectMissing, Error: "the original file is not in storage");
        if (text == "" && file.Size > 0) return new(SourceLookupStatus.Invalid, Error: "binary file");

        var lines = SplitLines(text);
        var maxLines = Math.Clamp(request.maxLines ?? MaxLines, 1, MaxLines);
        var start = Math.Max(1, request.startLine ?? 1);
        if (start > lines.Count) return new(SourceLookupStatus.Invalid, Error: $"start line {start} is beyond the end of the file ({lines.Count} lines)");
        var requestedEnd = Math.Min(request.endLine ?? lines.Count, lines.Count);
        var end = Math.Min(requestedEnd, start + maxLines - 1);
        if (end < start) return new(SourceLookupStatus.Invalid, Error: "end line is before start line");

        return new(SourceLookupStatus.Found, new SourceContentResponse(
            path,
            lines.Count,
            start,
            end,
            lines.GetRange(start - 1, end - start + 1),
            end < requestedEnd));
    }

    public static Regex? GlobToRegex(string? glob)
    {
        if (string.IsNullOrWhiteSpace(glob)) return null;
        var builder = new StringBuilder("^");
        var normalized = glob.Replace('\\', '/');
        for (var i = 0; i < normalized.Length; i++)
        {
            var c = normalized[i];
            if (c == '*' && i + 1 < normalized.Length && normalized[i + 1] == '*')
            {
                builder.Append(".*");
                i++;
                if (i + 1 < normalized.Length && normalized[i + 1] == '/') i++;
            }
            else if (c == '*') builder.Append("[^/]*");
            else if (c == '?') builder.Append("[^/]");
            else builder.Append(Regex.Escape(c.ToString()));
        }
        builder.Append('$');
        return new Regex(builder.ToString(), RegexOptions.IgnoreCase | RegexOptions.CultureInvariant, RegexTimeout);
    }

    public async Task<SourceLookup<SourceSearchResponse>> SearchAsync(int projectId, SourceSearchRequest request, CancellationToken cancellationToken = default)
    {
        var (status, access) = await AuthorizeAsync(projectId, request.userId, request.investigationId);
        if (status != SourceLookupStatus.Found) return new(status);

        if (string.IsNullOrEmpty(request.pattern) || request.pattern.Length > 200)
            return new(SourceLookupStatus.Invalid, Error: "pattern must be 1-200 characters");
        if (request.pathGlob != null && request.pathGlob.Contains(".."))
            return new(SourceLookupStatus.Invalid, Error: "path glob must be repository-relative");

        Regex? regex = null;
        if (request.isRegex)
        {
            try
            {
                regex = new Regex(request.pattern, RegexOptions.CultureInvariant, RegexTimeout);
            }
            catch (ArgumentException e)
            {
                return new(SourceLookupStatus.Invalid, Error: $"invalid regex: {e.Message}");
            }
        }

        var glob = GlobToRegex(request.pathGlob);
        var extensions = (request.extensions ?? new())
            .Select(e => e.StartsWith('.') ? e : "." + e)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        var maxResults = Math.Clamp(request.maxResults ?? 20, 1, MaxSearchResults);

        var files = MetricsAnalysisService.CodeFilesOf(await db.Files.Where(f => f.ProjectID == projectId).ToListAsync())
            .Where(f => extensions.Count == 0 || extensions.Contains(Path.GetExtension(f.RelativePath)))
            .Where(f => glob == null || glob.IsMatch(EvidenceJson.NormalizePath(f.RelativePath)))
            .ToList();

        var matches = new List<SourceMatchDto>();
        var truncated = files.Count > MaxSearchFiles;
        var searched = 0;
        var watch = Stopwatch.StartNew();

        foreach (var file in files.Take(MaxSearchFiles))
        {
            if (cancellationToken.IsCancellationRequested || watch.Elapsed > SearchBudget)
            {
                truncated = true;
                break;
            }

            var text = await ReadTextAsync(access!, projectId, file);
            searched++;
            if (string.IsNullOrEmpty(text)) continue;

            var lines = SplitLines(text);
            for (var i = 0; i < lines.Count; i++)
            {
                bool hit;
                try
                {
                    hit = regex != null ? regex.IsMatch(lines[i]) : lines[i].Contains(request.pattern, StringComparison.Ordinal);
                }
                catch (RegexMatchTimeoutException)
                {
                    return new(SourceLookupStatus.Invalid, Error: "regex evaluation timed out");
                }
                if (!hit) continue;

                var line = lines[i].Trim();
                matches.Add(new SourceMatchDto(
                    EvidenceJson.NormalizePath(file.RelativePath),
                    i + 1,
                    line.Length > MaxLineText ? line[..MaxLineText] : line));
                if (matches.Count >= maxResults)
                    return new(SourceLookupStatus.Found, new SourceSearchResponse(matches, true, searched));
            }
        }

        return new(SourceLookupStatus.Found, new SourceSearchResponse(matches, truncated, searched));
    }
}
