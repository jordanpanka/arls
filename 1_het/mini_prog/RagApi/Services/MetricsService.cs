using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using ef;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;

public class MetricsService
{
    private const int MaxLimit = 200;

    private readonly CodeDbContext db;
    private readonly MetricsThresholds currentThresholds;

    public MetricsService(CodeDbContext codeDbContext, IOptions<MetricsOptions> options)
    {
        db = codeDbContext;
        currentThresholds = options.Value.Thresholds;
    }

    public static async Task<MetricsLookupStatus> CheckProjectAccessAsync(CodeDbContext db, int userId, int projectId)
    {
        var owner = await db.Projects
            .Where(p => p.ID == projectId)
            .Select(p => new { OwnerId = p.Investigation.UserID })
            .FirstOrDefaultAsync();

        if (owner == null) return MetricsLookupStatus.ProjectNotFound;
        return owner.OwnerId == userId ? MetricsLookupStatus.Found : MetricsLookupStatus.Forbidden;
    }

    public Task<DbMetricsAnalysis?> LatestUsableAnalysisAsync(int projectId) =>
        db.MetricsAnalyses
            .Where(a => a.ProjectID == projectId && MetricsAnalysisStatus.Usable.Contains(a.Status))
            .OrderByDescending(a => a.CompletedAt)
            .ThenByDescending(a => a.ID)
            .FirstOrDefaultAsync();

    private async Task<(MetricsLookupStatus Status, DbMetricsAnalysis? Analysis)> ResolveAsync(int userId, int projectId)
    {
        var access = await CheckProjectAccessAsync(db, userId, projectId);
        if (access != MetricsLookupStatus.Found) return (access, null);

        var analysis = await LatestUsableAnalysisAsync(projectId);
        return analysis == null ? (MetricsLookupStatus.NoAnalysis, null) : (MetricsLookupStatus.Found, analysis);
    }

    public MetricsThresholds ThresholdsOf(DbMetricsAnalysis analysis)
    {
        if (string.IsNullOrWhiteSpace(analysis.ThresholdsJson)) return currentThresholds;
        try
        {
            return JsonSerializer.Deserialize<MetricsThresholds>(analysis.ThresholdsJson) ?? currentThresholds;
        }
        catch (JsonException)
        {
            return currentThresholds;
        }
    }

    public async Task<MetricsLookup<MetricsStatusDto>> GetStatusAsync(int userId, int projectId)
    {
        var access = await CheckProjectAccessAsync(db, userId, projectId);
        if (access != MetricsLookupStatus.Found) return new(access);

        var latest = await db.MetricsAnalyses
            .Where(a => a.ProjectID == projectId)
            .OrderByDescending(a => a.ID)
            .FirstOrDefaultAsync();
        var usable = await LatestUsableAnalysisAsync(projectId);

        return new(MetricsLookupStatus.Found, new MetricsStatusDto(
            latest == null ? null : ToDto(latest),
            usable == null ? null : ToDto(usable)));
    }

    public async Task<MetricsLookup<RepositoryMetricsDto>> GetRepositoryMetricsAsync(int userId, int projectId)
    {
        var (status, analysis) = await ResolveAsync(userId, projectId);
        if (analysis == null) return new(status);

        var thresholds = ThresholdsOf(analysis);
        var complexities = await FunctionsOf(analysis.ID).Select(f => f.CyclomaticComplexity).ToListAsync();

        return new(MetricsLookupStatus.Found, new RepositoryMetricsDto(
            ToDto(analysis),
            ToSummary(analysis, thresholds),
            MetricsAggregator.Distribution(complexities, thresholds),
            MetricsAggregator.ToDto(thresholds),
            ParseSkipped(analysis.SkippedFilesJson)));
    }

    public async Task<MetricsLookup<List<FileMetricDto>>> GetFileMetricsAsync(int userId, int projectId, string? sort, bool descending, int? limit)
    {
        var (status, analysis) = await ResolveAsync(userId, projectId);
        if (analysis == null) return new(status);

        var query = SortFiles(db.FileMetrics.Where(f => f.AnalysisID == analysis.ID), sort, descending);
        var files = await query.Take(Clamp(limit, MaxLimit)).ToListAsync();
        var thresholds = ThresholdsOf(analysis);

        return new(MetricsLookupStatus.Found, files.Select(f => ToDto(f, thresholds)).ToList());
    }

    public async Task<MetricsLookup<FileMetricsDetailDto>> GetFileDetailAsync(int userId, int projectId, string path)
    {
        var (status, analysis) = await ResolveAsync(userId, projectId);
        if (analysis == null) return new(status);

        var normalized = EvidenceJson.NormalizePath(path);
        var file = await db.FileMetrics
            .Include(f => f.Functions)
            .FirstOrDefaultAsync(f => f.AnalysisID == analysis.ID && f.Path == normalized);

        if (file == null) return new(MetricsLookupStatus.NotFound);

        var thresholds = ThresholdsOf(analysis);
        var functions = file.Functions
            .OrderByDescending(f => f.CyclomaticComplexity)
            .ThenBy(f => f.StartLine)
            .Select(f => ToDto(f, file, thresholds))
            .ToList();

        return new(MetricsLookupStatus.Found, new FileMetricsDetailDto(ToDto(analysis), ToDto(file, thresholds), functions));
    }

    public async Task<MetricsLookup<List<FunctionMetricDto>>> GetFunctionMetricsAsync(int userId, int projectId, string? path, string? sort, int? limit)
    {
        var (status, analysis) = await ResolveAsync(userId, projectId);
        if (analysis == null) return new(status);

        var query = FunctionsOf(analysis.ID);
        if (!string.IsNullOrWhiteSpace(path))
        {
            var normalized = EvidenceJson.NormalizePath(path);
            query = query.Where(f => f.FileMetric.Path == normalized);
        }

        query = sort?.ToLowerInvariant() switch
        {
            "nloc" => query.OrderByDescending(f => f.Nloc),
            "parameters" => query.OrderByDescending(f => f.ParameterCount),
            "fanin" => query.OrderByDescending(f => f.FanIn),
            "fanout" => query.OrderByDescending(f => f.FanOut),
            "line" => query.OrderBy(f => f.FileMetric.Path).ThenBy(f => f.StartLine),
            _ => query.OrderByDescending(f => f.CyclomaticComplexity).ThenByDescending(f => f.Nloc),
        };

        return new(MetricsLookupStatus.Found, await ToFunctionDtosAsync(query.Take(Clamp(limit, MaxLimit)), analysis));
    }

    public async Task<MetricsLookup<HotspotsDto>> GetComplexityHotspotsAsync(int userId, int projectId, int? limit)
    {
        var (status, analysis) = await ResolveAsync(userId, projectId);
        return analysis == null ? new(status) : new(MetricsLookupStatus.Found, await HotspotsAsync(analysis, "complexity", Clamp(limit, 50)));
    }

    public async Task<MetricsLookup<HotspotsDto>> GetDependencyHotspotsAsync(int userId, int projectId, int? limit)
    {
        var (status, analysis) = await ResolveAsync(userId, projectId);
        return analysis == null ? new(status) : new(MetricsLookupStatus.Found, await HotspotsAsync(analysis, "dependency", Clamp(limit, 50)));
    }

    public async Task<MetricsLookup<HotspotsDto>> GetMaintainabilityHotspotsAsync(int userId, int projectId, int? limit)
    {
        var (status, analysis) = await ResolveAsync(userId, projectId);
        return analysis == null ? new(status) : new(MetricsLookupStatus.Found, await HotspotsAsync(analysis, "maintainability", Clamp(limit, 50)));
    }

    public async Task<HotspotsDto> HotspotsAsync(DbMetricsAnalysis analysis, string focus, int limit)
    {
        var thresholds = ThresholdsOf(analysis);
        var files = db.FileMetrics.Where(f => f.AnalysisID == analysis.ID);
        var functions = FunctionsOf(analysis.ID);
        var kind = focus;

        switch (focus)
        {
            case "dependency":
                files = files.Where(f => f.FanIn != null)
                    .OrderByDescending(f => f.FanIn + f.FanOut).ThenByDescending(f => f.FanIn);
                functions = functions.Where(f => f.FanIn != null)
                    .OrderByDescending(f => f.FanIn + f.FanOut).ThenByDescending(f => f.FanIn);
                break;
            case "maintainability":
                files = files
                    .OrderByDescending(f => f.HighComplexityFunctionCount + f.LongFunctionCount + f.ManyParameterFunctionCount)
                    .ThenByDescending(f => f.MaxComplexity).ThenByDescending(f => f.Nloc);
                functions = functions.OrderByDescending(f => f.Nloc).ThenByDescending(f => f.CyclomaticComplexity);
                break;
            case "size":
                files = files.OrderByDescending(f => f.Nloc);
                functions = functions.OrderByDescending(f => f.Nloc);
                break;
            default:
                kind = "complexity";
                files = files.Where(f => f.MaxComplexity != null)
                    .OrderByDescending(f => f.MaxComplexity).ThenByDescending(f => f.AverageComplexity);
                functions = functions.OrderByDescending(f => f.CyclomaticComplexity).ThenByDescending(f => f.Nloc);
                break;
        }

        var fileRows = await files.Take(limit).ToListAsync();
        return new HotspotsDto(
            kind,
            fileRows.Select(f => ToDto(f, thresholds)).ToList(),
            await ToFunctionDtosAsync(functions.Take(limit), analysis));
    }

    public async Task<List<FileMetricDto>> GetMetricsForFilesAsync(DbMetricsAnalysis analysis, IEnumerable<string> paths)
    {
        var normalized = paths.Select(EvidenceJson.NormalizePath).Where(p => p != "").Distinct().ToList();
        if (normalized.Count == 0) return new();

        var thresholds = ThresholdsOf(analysis);
        var rows = await db.FileMetrics
            .Where(f => f.AnalysisID == analysis.ID && normalized.Contains(f.Path))
            .ToListAsync();

        return rows
            .OrderBy(f => normalized.IndexOf(f.Path))
            .Select(f => ToDto(f, thresholds))
            .ToList();
    }

    public async Task<List<FunctionMetricDto>> GetMetricsForSymbolsAsync(DbMetricsAnalysis analysis, IEnumerable<MetricsSymbolRef> symbols)
    {
        var refs = symbols
            .Select(s => (Path: EvidenceJson.NormalizePath(s.path), Name: MetricsAggregator.ShortName(s.name), s.startLine))
            .Where(s => s.Path != "" && s.Name != "")
            .ToList();
        if (refs.Count == 0) return new();

        var paths = refs.Select(r => r.Path).Distinct().ToList();
        var names = refs.Select(r => r.Name).Distinct().ToList();

        var candidates = await FunctionsOf(analysis.ID)
            .Include(f => f.FileMetric)
            .Where(f => paths.Contains(f.FileMetric.Path) && names.Contains(f.Name))
            .ToListAsync();

        var thresholds = ThresholdsOf(analysis);
        var result = new List<FunctionMetricDto>();

        foreach (var symbol in refs)
        {
            var match = candidates
                .Where(f => f.FileMetric.Path == symbol.Path && f.Name == symbol.Name)
                .OrderBy(f => symbol.startLine.HasValue ? Math.Abs(f.StartLine - symbol.startLine.Value) : 0)
                .FirstOrDefault();

            if (match != null && result.All(r => r.Id != match.ID))
                result.Add(ToDto(match, match.FileMetric, thresholds));
        }

        return result;
    }

    public async Task<MetricsLookup<RagMetricsResponse>> GetRagEvidenceAsync(int projectId, RagMetricsRequest request)
    {
        var project = await db.Projects
            .Where(p => p.ID == projectId)
            .Select(p => new { p.InvestigationID, OwnerId = p.Investigation.UserID })
            .FirstOrDefaultAsync();

        if (project == null) return new(MetricsLookupStatus.ProjectNotFound);
        if (project.OwnerId != request.userId || project.InvestigationID != request.investigationId)
            return new(MetricsLookupStatus.Forbidden);

        var analysis = await LatestUsableAnalysisAsync(projectId);
        if (analysis == null) return new(MetricsLookupStatus.NoAnalysis);

        var thresholds = ThresholdsOf(analysis);
        var limit = Clamp(request.limit, 10);
        var files = await GetMetricsForFilesAsync(analysis, request.paths ?? new());
        var functions = await GetMetricsForSymbolsAsync(analysis, request.symbols ?? new());

        RepositorySummaryDto? repository = null;
        HotspotsDto? hotspots = null;
        if (request.includeRepository)
        {
            repository = ToSummary(analysis, thresholds);
            hotspots = await HotspotsAsync(analysis, request.focus ?? "complexity", limit);
        }

        return new(MetricsLookupStatus.Found, new RagMetricsResponse(
            true,
            ToDto(analysis),
            MetricsAggregator.ToDto(thresholds),
            repository,
            files,
            functions,
            hotspots?.Files ?? new(),
            hotspots?.Functions ?? new()));
    }

    private IQueryable<DbFunctionMetric> FunctionsOf(int analysisId) =>
        db.FunctionMetrics.Where(f => f.FileMetric.AnalysisID == analysisId);

    private async Task<List<FunctionMetricDto>> ToFunctionDtosAsync(IQueryable<DbFunctionMetric> query, DbMetricsAnalysis analysis)
    {
        var thresholds = ThresholdsOf(analysis);
        var rows = await query.Include(f => f.FileMetric).ToListAsync();
        return rows.Select(f => ToDto(f, f.FileMetric, thresholds)).ToList();
    }

    private static IQueryable<DbFileMetric> SortFiles(IQueryable<DbFileMetric> query, string? sort, bool descending)
    {
        IOrderedQueryable<DbFileMetric> Order<T>(System.Linq.Expressions.Expression<Func<DbFileMetric, T>> key) =>
            descending ? query.OrderByDescending(key) : query.OrderBy(key);

        return (sort?.ToLowerInvariant()) switch
        {
            "path" => Order(f => f.Path),
            "nloc" => Order(f => f.Nloc),
            "functions" => Order(f => f.FunctionCount),
            "averagecomplexity" => Order(f => f.AverageComplexity),
            "fanin" => Order(f => f.FanIn),
            "fanout" => Order(f => f.FanOut),
            "highcomplexity" => Order(f => f.HighComplexityFunctionCount),
            _ => Order(f => f.MaxComplexity).ThenByDescending(f => f.AverageComplexity),
        };
    }

    private static int Clamp(int? limit, int max) => Math.Clamp(limit ?? 20, 1, max);

    private static List<SkippedFileDto> ParseSkipped(string? json)
    {
        if (string.IsNullOrWhiteSpace(json)) return new();
        try
        {
            return JsonSerializer.Deserialize<List<SkippedFileDto>>(json, EvidenceJson.Options) ?? new();
        }
        catch (JsonException)
        {
            return new();
        }
    }

    private static List<List<string>> ParseCycles(string? json)
    {
        if (string.IsNullOrWhiteSpace(json)) return new();
        try
        {
            return JsonSerializer.Deserialize<List<List<string>>>(json) ?? new();
        }
        catch (JsonException)
        {
            return new();
        }
    }

    public static MetricsAnalysisDto ToDto(DbMetricsAnalysis a) => new(
        a.ID, a.ProjectID, a.RepositoryID, a.Status, a.StaticStatus, a.GraphStatus, a.ErrorMessage, a.Trigger,
        a.Branch, a.CommitSha, a.CreatedAt, a.StartedAt, a.CompletedAt, a.TotalDurationMs, a.StaticDurationMs,
        a.GraphDurationMs, a.FilesAnalyzed, a.FilesSkipped, a.StaticAnalyzer, a.GraphAnalyzer);

    public static RepositorySummaryDto ToSummary(DbMetricsAnalysis a, MetricsThresholds t) => new(
        a.FilesAnalyzed,
        a.TotalNloc,
        a.TotalFunctions,
        a.TotalClasses,
        a.AverageComplexity.HasValue ? Math.Round(a.AverageComplexity.Value, 2) : null,
        a.MaxComplexity,
        a.MaxComplexity.HasValue ? MetricsAggregator.Categorize(a.MaxComplexity.Value, t) : null,
        a.HighComplexityFunctionCount,
        a.LongFunctionCount,
        a.ManyParameterFunctionCount,
        a.DependencyCount,
        a.CycleCount,
        a.AverageFanIn.HasValue ? Math.Round(a.AverageFanIn.Value, 2) : null,
        a.AverageFanOut.HasValue ? Math.Round(a.AverageFanOut.Value, 2) : null,
        a.MaxFanIn,
        a.MaxFanOut,
        a.MaxDependencyDepth,
        ParseCycles(a.CyclesJson));

    public static FileMetricDto ToDto(DbFileMetric f, MetricsThresholds t) => new(
        f.ID, f.FileID, f.Path, f.Language, f.Nloc, f.TokenCount, f.FunctionCount, f.ClassCount,
        f.AverageComplexity.HasValue ? Math.Round(f.AverageComplexity.Value, 2) : null,
        f.MaxComplexity,
        f.MaxComplexity.HasValue ? MetricsAggregator.Categorize(f.MaxComplexity.Value, t) : null,
        f.HighComplexityFunctionCount,
        f.AverageFunctionNloc.HasValue ? Math.Round(f.AverageFunctionNloc.Value, 2) : null,
        f.MaxFunctionNloc, f.LongFunctionCount, f.ManyParameterFunctionCount, f.FanIn, f.FanOut, f.ImportCount);

    public static FunctionMetricDto ToDto(DbFunctionMetric f, DbFileMetric file, MetricsThresholds t) => new(
        f.ID, file.FileID, file.Path, f.Name, f.LongName, f.ClassName, f.StartLine, f.EndLine, f.Nloc,
        f.CyclomaticComplexity, MetricsAggregator.Categorize(f.CyclomaticComplexity, t), f.TokenCount,
        f.ParameterCount, f.Length, f.FanIn, f.FanOut,
        MetricsAggregator.IsLong(f.Nloc, t), MetricsAggregator.HasManyParameters(f.ParameterCount, t));
}
