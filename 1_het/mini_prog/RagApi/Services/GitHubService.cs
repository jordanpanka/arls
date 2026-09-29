using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Configuration;


public class RepositoryEntry
{
    public string Path { get; set; } = "";
    public long Length { get; set; }

    internal ZipArchiveEntry Source { get; set; } = default!;
}

public sealed class RepositoryFile : IDisposable
{
    public IFormFile File { get; }
    public string RelativePath { get; }

    private readonly MemoryStream buffer;

    internal RepositoryFile(IFormFile file, string relativePath, MemoryStream content)
    {
        File = file;
        RelativePath = relativePath;
        buffer = content;
    }

    public void Dispose() => buffer.Dispose();
}

public sealed class RepositorySnapshot : IDisposable
{
    private readonly FileStream file;
    private readonly ZipArchive archive;
    private readonly List<RepositoryEntry> entries = new();

    public string CommitSha { get; }
    public int SkippedCount { get; set; }
    public int TotalEntries { get; set; }

    public IReadOnlyList<RepositoryEntry> Entries => entries;

    internal RepositorySnapshot(string commitSha, FileStream tempFile, ZipArchive zip)
    {
        CommitSha = commitSha;
        file = tempFile;
        archive = zip;
    }

    internal void Add(RepositoryEntry entry) => entries.Add(entry);

    public RepositoryFile Open(RepositoryEntry entry)
    {
        // A ShouldIndex MaxFileBytes-ra szűrt, tehát a méret biztosan elfér
        // int-en; a pontos kapacitás megspórolja a MemoryStream újrafoglalásait.
        var buffer = new MemoryStream((int)entry.Length);

        using (var content = entry.Source.Open())
        {
            content.CopyTo(buffer);
        }

        buffer.Position = 0;

        var fileName = Path.GetFileName(entry.Path);
        var formFile = new FormFile(buffer, 0, buffer.Length, "files", fileName)
        {
            Headers = new HeaderDictionary()
        };
        formFile.ContentType = GitHubService.ContentTypeFor(Path.GetExtension(fileName));

        return new RepositoryFile(formFile, entry.Path, buffer);
    }

    public void Dispose()
    {
        archive.Dispose();

        // A temp fájl DeleteOnClose-szal nyílt, tehát itt tűnik el — akkor is,
        // ha az import félúton elhasalt.
        file.Dispose();
    }
}

public class RateLimitState
{
    public int Limit { get; set; }
    public int Remaining { get; set; }
    public DateTime ResetUtc { get; set; }
}

public class GitHubService
{
    private readonly HttpClient httpClient;

    private readonly string? token;

    private const string UserAgent = "mini-prog-rag";
    private const string ApiRoot = "https://api.github.com";

    private static readonly string[] IgnoredSegments =
    {
        "node_modules", "bin", "obj", "dist", "build", "out",
        ".git", ".github", ".venv", "venv", "__pycache__", "site-packages",
        ".next", ".nuxt", "target", "vendor", "ragas_env", ".pytest_cache",
        ".mypy_cache", ".idea", ".vs", "coverage", "htmlcov", "packages"
    };

    private static readonly HashSet<string> AllowedExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        // code
        ".cs", ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs",
        ".php", ".cpp", ".c", ".h", ".hpp",
        // structured / configuration
        ".json", ".yaml", ".yml", ".xml", ".toml", ".ini", ".cfg", ".conf",
        ".properties", ".gradle", ".sql",
        // documentation
        ".md", ".txt", ".rst", ".pdf"
    };

    private static readonly HashSet<string> AllowedFilenames = new(StringComparer.OrdinalIgnoreCase)
    {
        "dockerfile", "containerfile", "makefile", "jenkinsfile", "vagrantfile",
        "procfile", "codeowners", "gemfile", "rakefile",
        "readme", "license", "licence", "changelog", "contributing",
        "authors", "notice", "todo"
    };

    private static readonly HashSet<string> BlockedFilenames = new(StringComparer.OrdinalIgnoreCase)
    {
        ".env", "id_rsa", "id_ed25519", ".npmrc", ".pypirc"
    };

    private const long MaxFileBytes = 1024 * 1024;

    private const int MaxFiles = 2000;

    /// <summary>Egy import két API-kérést használ: a SHA feloldását és a zipballt.</summary>
    public const int RequestsPerImport = 2;

    public GitHubService(HttpClient http, IConfiguration configuration)
    {
        httpClient = http;

        
        token = configuration["GitHub:Token"];
    }

    private HttpRequestMessage BuildRequest(HttpMethod method, string url)
    {
        var request = new HttpRequestMessage(method, url);
        request.Headers.UserAgent.ParseAdd(UserAgent);
        request.Headers.Accept.ParseAdd("application/vnd.github+json");

        if (!string.IsNullOrWhiteSpace(token))
        {
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        }

        return request;
    }

    
    public async Task<ServiceResult> GetRateLimitAsync(CancellationToken cancellationToken = default)
    {
        try
        {
            using var request = BuildRequest(HttpMethod.Get, $"{ApiRoot}/rate_limit");
            using var response = await httpClient.SendAsync(request, cancellationToken);

            if (!response.IsSuccessStatusCode)
                return ServiceResult.Fail($"GitHub returned {(int)response.StatusCode} for /rate_limit.");

            using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync(cancellationToken));
            var core = doc.RootElement.GetProperty("resources").GetProperty("core");

            return ServiceResult.Success(new RateLimitState
            {
                Limit = core.GetProperty("limit").GetInt32(),
                Remaining = core.GetProperty("remaining").GetInt32(),
                ResetUtc = DateTimeOffset
                    .FromUnixTimeSeconds(core.GetProperty("reset").GetInt64())
                    .UtcDateTime
            });
        }
        catch (Exception ex)
        {
            return ServiceResult.Fail($"Could not read the GitHub rate limit: {ex.Message}");
        }
    }

    public async Task<ServiceResult> GetCommitShaAsync(
        string owner, string repo, string reference, CancellationToken cancellationToken = default)
    {
        try
        {
            using var request = BuildRequest(
                HttpMethod.Get,
                $"{ApiRoot}/repos/{owner}/{repo}/commits/{reference}");

            using var response = await httpClient.SendAsync(request, cancellationToken);

            if (!response.IsSuccessStatusCode)
            {
                var body = await response.Content.ReadAsStringAsync(cancellationToken);
                return ServiceResult.Fail($"{owner}/{repo}@{reference}: {DescribeFailure(response, body)}");
            }

            using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync(cancellationToken));
            var sha = doc.RootElement.GetProperty("sha").GetString() ?? "";
            return ServiceResult.Success(sha);
        }
        catch (Exception ex)
        {
            return ServiceResult.Fail($"Could not resolve {owner}/{repo}@{reference}: {ex.Message}");
        }
    }

    public async Task<ServiceResult> FetchSnapshotAsync(
        string owner, string repo, string reference, CancellationToken cancellationToken = default)
    {
        var shaResult = await GetCommitShaAsync(owner, repo, reference, cancellationToken);
        if (!shaResult.Ok) return shaResult;

        var sha = (string)shaResult.Data!;

        FileStream? buffer = null;

        try
        {
            
            using var request = BuildRequest(
                HttpMethod.Get,
                $"{ApiRoot}/repos/{owner}/{repo}/zipball/{sha}");

            using var response = await httpClient.SendAsync(
                request, HttpCompletionOption.ResponseHeadersRead, cancellationToken);

            if (!response.IsSuccessStatusCode)
            {
                var body = await response.Content.ReadAsStringAsync(cancellationToken);
                return ServiceResult.Fail($"Could not download {owner}/{repo}: {DescribeFailure(response, body)}");
            }

            
            buffer = CreateTempFile();
            await response.Content.CopyToAsync(buffer, cancellationToken);
            buffer.Position = 0;

            var snapshot = BuildSnapshot(buffer, sha);

            // Innentől a snapshot birtokolja a temp fájlt, ő is zárja le.
            buffer = null;

            return ServiceResult.Success(snapshot);
        }
        catch (Exception ex)
        {
            return ServiceResult.Fail($"Failed to fetch {owner}/{repo}: {ex.Message}");
        }
        finally
        {
            buffer?.Dispose();
        }
    }

    private static FileStream CreateTempFile()
    {
        var path = Path.Combine(Path.GetTempPath(), $"repo-{Guid.NewGuid():N}.zip");

        // DeleteOnClose: a fájl a Dispose-nál eltűnik, akkor is, ha az import
        // kivétellel áll le, tehát nem szivárog lemez.
        return new FileStream(
            path, FileMode.CreateNew, FileAccess.ReadWrite, FileShare.None,
            bufferSize: 81920, FileOptions.DeleteOnClose);
    }

    
    private static RepositorySnapshot BuildSnapshot(FileStream buffer, string sha)
    {
        var archive = new ZipArchive(buffer, ZipArchiveMode.Read);
        var snapshot = new RepositorySnapshot(sha, buffer, archive);

        foreach (var entry in archive.Entries)
        {
            // Directory entries have an empty Name.
            if (string.IsNullOrWhiteSpace(entry.Name)) continue;

            snapshot.TotalEntries++;

            var path = StripArchiveRoot(entry.FullName);

            if (!ShouldIndex(path, entry.Length) || snapshot.Entries.Count >= MaxFiles)
            {
                snapshot.SkippedCount++;
                continue;
            }

            snapshot.Add(new RepositoryEntry
            {
                Path = path,
                Length = entry.Length,
                Source = entry
            });
        }

        return snapshot;
    }

    private string DescribeFailure(HttpResponseMessage response, string body)
    {
        var status = (int)response.StatusCode;

        // Kimerült kvótánál a GitHub 403-at vagy 429-et ad, és a remaining 0.
        if ((status == 403 || status == 429) && ReadIntHeader(response, "x-ratelimit-remaining") == 0)
        {
            var limit = ReadIntHeader(response, "x-ratelimit-limit");
            var reset = ReadResetHeader(response);

            var scope = limit.HasValue ? $" ({limit} requests/hour)" : "";
            var when = reset.HasValue ? $" It resets at {reset.Value:HH:mm} UTC." : "";
            var hint = string.IsNullOrWhiteSpace(token)
                ? " Set GitHub:Token to raise the limit from 60 to 5000 requests/hour."
                : "";

            return $"GitHub rate limit exhausted{scope}.{when}{hint}";
        }

        if (status == 401)
            return "GitHub rejected the configured token (GitHub:Token); it may be expired or revoked.";

        if (status == 404)
            return string.IsNullOrWhiteSpace(token)
                ? "Repository not found. Private repositories need GitHub:Token to be configured."
                : "Repository not found, or the configured token cannot see it.";

        // A body lehet több kilobájt is, a hibaüzenet pedig 1000 karakterre
        // csonkolva megy a DB-be.
        var trimmed = body.Length > 300 ? body[..300] : body;
        return $"GitHub returned {status}: {trimmed}";
    }

    private static int? ReadIntHeader(HttpResponseMessage response, string name)
    {
        if (!response.Headers.TryGetValues(name, out var values)) return null;

        var raw = values.FirstOrDefault();
        return int.TryParse(raw, NumberStyles.Integer, CultureInfo.InvariantCulture, out var parsed)
            ? parsed
            : null;
    }

    private static DateTime? ReadResetHeader(HttpResponseMessage response)
    {
        if (!response.Headers.TryGetValues("x-ratelimit-reset", out var values)) return null;

        var raw = values.FirstOrDefault();
        return long.TryParse(raw, NumberStyles.Integer, CultureInfo.InvariantCulture, out var epoch)
            ? DateTimeOffset.FromUnixTimeSeconds(epoch).UtcDateTime
            : null;
    }

    private static string StripArchiveRoot(string fullName)
    {
        var path = fullName.Replace("\\", "/").TrimStart('/');

        var slash = path.IndexOf('/');
        return slash >= 0 ? path[(slash + 1)..] : path;
    }

    private static bool ShouldIndex(string path, long length)
    {
        if (string.IsNullOrWhiteSpace(path)) return false;
        if (path.Contains("..")) return false;
        if (length <= 0 || length > MaxFileBytes) return false;

        var segments = path.Split('/', StringSplitOptions.RemoveEmptyEntries);
        if (segments.Length == 0) return false;

        // Compare whole path segments: a blanket Contains() would also reject
        // legitimate files such as "src/binary_search.py" because of "bin".
        if (segments.Take(segments.Length - 1).Any(s => IgnoredSegments.Contains(s, StringComparer.OrdinalIgnoreCase)))
            return false;

        var fileName = segments[^1];
        if (BlockedFilenames.Contains(fileName)) return false;

        var extension = Path.GetExtension(fileName);


        return string.IsNullOrEmpty(extension)
            ? AllowedFilenames.Contains(fileName)
            : AllowedExtensions.Contains(extension);
    }

    internal static string ContentTypeFor(string extension) => extension.ToLowerInvariant() switch
    {
        ".md" => "text/markdown",
        ".json" => "application/json",
        ".xml" => "application/xml",
        ".yaml" or ".yml" => "application/yaml",
        ".pdf" => "application/pdf",
        _ => "text/plain"
    };
}
