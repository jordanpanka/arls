using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using ef;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

public class MetricsAnalysisService
{
    private const int MaxStoredSkipped = 500;
    private const int MaxErrorLength = 1000;

    private readonly CodeDbContext db;
    private readonly HttpClient httpClient;
    private readonly IConfiguration configuration;
    private readonly MinioService minioService;
    private readonly MetricsAnalysisQueue queue;
    private readonly MetricsOptions options;
    private readonly ILogger<MetricsAnalysisService> logger;

    public MetricsAnalysisService(
        CodeDbContext codeDbContext,
        HttpClient client,
        IConfiguration config,
        MinioService minio,
        MetricsAnalysisQueue analysisQueue,
        IOptions<MetricsOptions> metricsOptions,
        ILogger<MetricsAnalysisService> log)
    {
        db = codeDbContext;
        httpClient = client;
        configuration = config;
        minioService = minio;
        queue = analysisQueue;
        options = metricsOptions.Value;
        logger = log;
    }

    public async Task<MetricsLookup<AnalyzeMetricsResponse>> QueueAsync(int userId, int projectId, bool force)
    {
        var access = await MetricsService.CheckProjectAccessAsync(db, userId, projectId);
        if (access != MetricsLookupStatus.Found) return new(access);

        return new(MetricsLookupStatus.Found, await QueueInternalAsync(projectId, force, MetricsTrigger.Manual));
    }

    public async Task<AnalyzeMetricsResponse?> QueueAfterImportAsync(int projectId)
    {
        if (!options.AutoAnalyzeAfterImport) return null;
        return await QueueInternalAsync(projectId, force: false, MetricsTrigger.Import);
    }

    private async Task<AnalyzeMetricsResponse> QueueInternalAsync(int projectId, bool force, string trigger)
    {
        var running = await db.MetricsAnalyses
            .Where(a => a.ProjectID == projectId && MetricsAnalysisStatus.InFlight.Contains(a.Status))
            .OrderByDescending(a => a.ID)
            .FirstOrDefaultAsync();

        if (running != null) return new(running.ID, running.Status, Reused: true);

        var repository = await db.Repositories
            .Where(r => r.ProjectID == projectId && r.Status == RepositoryStatus.Ready)
            .OrderByDescending(r => r.IndexedAt)
            .FirstOrDefaultAsync();

        var fileSetHash = FileSetHash(await CodeFilesAsync(projectId));

        if (!force)
        {
            var latest = await db.MetricsAnalyses
                .Where(a => a.ProjectID == projectId && MetricsAnalysisStatus.Usable.Contains(a.Status))
                .OrderByDescending(a => a.ID)
                .FirstOrDefaultAsync();

            var unchanged = latest != null
                && latest.FileSetHash == fileSetHash
                && (latest.CommitSha ?? "") == (repository?.CommitSha ?? "")
                && latest.ThresholdsJson == JsonSerializer.Serialize(options.Thresholds);

            if (unchanged) return new(latest!.ID, latest.Status, Reused: true);
        }

        var analysis = new DbMetricsAnalysis
        {
            ProjectID = projectId,
            RepositoryID = repository?.ID,
            Branch = repository?.Reference,
            CommitSha = string.IsNullOrEmpty(repository?.CommitSha) ? null : repository!.CommitSha,
            Trigger = trigger,
            Status = MetricsAnalysisStatus.Queued,
            FileSetHash = fileSetHash,
            ThresholdsJson = JsonSerializer.Serialize(options.Thresholds),
        };

        db.MetricsAnalyses.Add(analysis);
        await db.SaveChangesAsync();
        await queue.EnqueueAsync(analysis.ID);

        return new(analysis.ID, analysis.Status, Reused: false);
    }

    public async Task RunAsync(int analysisId, CancellationToken cancellationToken = default)
    {
        var analysis = await db.MetricsAnalyses.FirstOrDefaultAsync(a => a.ID == analysisId, cancellationToken);
        if (analysis == null) return;

        var context = await db.Projects
            .Where(p => p.ID == analysis.ProjectID)
            .Select(p => new { InvId = p.InvestigationID, UserId = p.Investigation.UserID })
            .FirstOrDefaultAsync(cancellationToken);

        if (context == null)
        {
            await MarkFailedAsync(analysis, "Project disappeared before the analysis started.");
            return;
        }

        var total = Stopwatch.StartNew();
        analysis.Status = MetricsAnalysisStatus.Running;
        analysis.StartedAt = DateTime.UtcNow;
        await db.SaveChangesAsync(cancellationToken);

        try
        {
            var thresholds = JsonSerializer.Deserialize<MetricsThresholds>(analysis.ThresholdsJson) ?? options.Thresholds;
            var codeFiles = await CodeFilesAsync(analysis.ProjectID);
            var skipped = new List<SkippedFileDto>();
            var analyzed = new List<AiFileMetrics>();

            var staticWatch = Stopwatch.StartNew();
            var batchSize = Math.Max(1, options.StaticBatchSize);

            for (var offset = 0; offset < codeFiles.Count; offset += batchSize)
            {
                cancellationToken.ThrowIfCancellationRequested();
                var batch = new List<(string Path, byte[] Content)>();

                foreach (var file in codeFiles.Skip(offset).Take(batchSize))
                {
                    var bytes = await minioService.ReadObjectAsync(
                        MinioService.ObjectName(context.UserId, context.InvId, analysis.ProjectID, file.RelativePath));

                    if (bytes == null) skipped.Add(new SkippedFileDto(file.RelativePath, "missing_in_storage"));
                    else batch.Add((file.RelativePath, bytes));
                }

                if (batch.Count == 0) continue;

                var result = await PostStaticAsync(batch, cancellationToken);
                analyzed.AddRange(result.Files);
                skipped.AddRange(result.Skipped.Select(s => new SkippedFileDto(s.Path, s.Reason)));
                analysis.StaticAnalyzer = result.Analyzer;
            }

            staticWatch.Stop();
            analysis.StaticDurationMs = staticWatch.Elapsed.TotalMilliseconds;
            analysis.StaticStatus = MetricsPhaseStatus.Completed;

            var fileIds = codeFiles.ToDictionary(f => EvidenceJson.NormalizePath(f.RelativePath), f => f.ID);
            var files = analyzed.Select(f =>
            {
                var metric = MetricsAggregator.BuildFile(f, thresholds);
                metric.FileID = fileIds.TryGetValue(metric.Path, out var id) ? id : null;
                return metric;
            }).ToList();

            var graphWatch = Stopwatch.StartNew();
            var graph = await TryGraphAsync(analysis, context.UserId, context.InvId, cancellationToken);
            graphWatch.Stop();
            analysis.GraphDurationMs = graphWatch.Elapsed.TotalMilliseconds;

            if (graph != null)
            {
                MetricsAggregator.ApplyGraph(files, graph);
                analysis.GraphAnalyzer = graph.Analyzer;
                analysis.CyclesJson = JsonSerializer.Serialize(graph.Cycles);
            }

            MetricsAggregator.ApplyRepository(analysis, files, graph, thresholds);
            analysis.Files = files;
            analysis.FilesSkipped = skipped.Count;
            analysis.SkippedFilesJson = JsonSerializer.Serialize(skipped.Take(MaxStoredSkipped), EvidenceJson.Options);
            analysis.Status = graph != null ? MetricsAnalysisStatus.Completed : MetricsAnalysisStatus.Partial;
            analysis.CompletedAt = DateTime.UtcNow;
            analysis.TotalDurationMs = total.Elapsed.TotalMilliseconds;

            await db.SaveChangesAsync(cancellationToken);

            logger.LogInformation(
                "Metrics analysis {AnalysisId} for project {ProjectId}: {Status}, {Analyzed} files analyzed, {Skipped} skipped, " +
                "{Functions} functions; total {TotalMs:F0} ms (static {StaticMs:F0} ms, graph {GraphMs:F0} ms)",
                analysis.ID, analysis.ProjectID, analysis.Status, analysis.FilesAnalyzed, analysis.FilesSkipped,
                analysis.TotalFunctions, analysis.TotalDurationMs, analysis.StaticDurationMs, analysis.GraphDurationMs);
        }
        catch (OperationCanceledException)
        {
            await MarkFailedAsync(analysis, "Analysis stopped because the backend is shutting down.");
        }
        catch (Exception ex)
        {
            logger.LogError(ex, "Metrics analysis {AnalysisId} failed", analysis.ID);
            analysis.StaticStatus = analysis.StaticStatus == MetricsPhaseStatus.Completed
                ? analysis.StaticStatus
                : MetricsPhaseStatus.Failed;
            await MarkFailedAsync(analysis, ex.Message);
        }
    }

    private async Task<AiStaticResult> PostStaticAsync(List<(string Path, byte[] Content)> batch, CancellationToken cancellationToken)
    {
        using var form = new MultipartFormDataContent();
        foreach (var (path, content) in batch)
        {
            var part = new ByteArrayContent(content);
            part.Headers.ContentType = new MediaTypeHeaderValue("application/octet-stream");
            form.Add(part, "files", System.IO.Path.GetFileName(path));
            form.Add(new StringContent(path, Encoding.UTF8), "paths");
        }

        var response = await httpClient.PostAsync($"{configuration["AI:PythonUrl"]}/api/metrics/static", form, cancellationToken);
        var body = await response.Content.ReadAsStringAsync(cancellationToken);

        if (!response.IsSuccessStatusCode)
            throw new InvalidOperationException($"Static analysis failed ({(int)response.StatusCode}): {Truncate(body)}");

        var result = JsonSerializer.Deserialize<AiServiceResult<AiStaticResult>>(body, EvidenceJson.Options);
        if (result is not { IsSuccess: true, Data: not null })
            throw new InvalidOperationException($"Static analysis failed: {result?.Message ?? Truncate(body)}");

        return result.Data;
    }

    private async Task<AiGraphResult?> TryGraphAsync(DbMetricsAnalysis analysis, int userId, int invId, CancellationToken cancellationToken)
    {
        try
        {
            var response = await httpClient.PostAsJsonAsync(
                $"{configuration["AI:PythonUrl"]}/api/metrics/graph",
                new { userId, investigationId = invId, projectId = analysis.ProjectID },
                cancellationToken);
            var body = await response.Content.ReadAsStringAsync(cancellationToken);

            var result = response.IsSuccessStatusCode
                ? JsonSerializer.Deserialize<AiServiceResult<AiGraphResult>>(body, EvidenceJson.Options)
                : null;

            if (result is { IsSuccess: true, Data: not null })
            {
                analysis.GraphStatus = MetricsPhaseStatus.Completed;
                return result.Data;
            }

            analysis.GraphStatus = MetricsPhaseStatus.Failed;
            analysis.ErrorMessage = Truncate($"Graph metrics unavailable: {result?.Message ?? body}");
        }
        catch (Exception ex) when (ex is HttpRequestException or JsonException or TaskCanceledException && !cancellationToken.IsCancellationRequested)
        {
            analysis.GraphStatus = MetricsPhaseStatus.Failed;
            analysis.ErrorMessage = Truncate($"Graph metrics unavailable: {ex.Message}");
        }

        logger.LogWarning("Metrics analysis {AnalysisId}: graph metrics failed, keeping static metrics. {Error}",
            analysis.ID, analysis.ErrorMessage);
        return null;
    }

    private async Task<List<DbFile>> CodeFilesAsync(int projectId)
    {
        var files = await db.Files.Where(f => f.ProjectID == projectId).ToListAsync();

        return files
            .Where(f => SourceLanguage.IsCode(f.RelativePath))
            .GroupBy(f => EvidenceJson.NormalizePath(f.RelativePath))
            .Select(g => g.OrderBy(f => f.ID).First())
            .OrderBy(f => f.RelativePath, StringComparer.Ordinal)
            .ToList();
    }

    private static string FileSetHash(IEnumerable<DbFile> files)
    {
        var text = string.Join("\n", files.Select(f => $"{EvidenceJson.NormalizePath(f.RelativePath)}:{f.Size}"));
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(text)));
    }

    private async Task MarkFailedAsync(DbMetricsAnalysis analysis, string error)
    {
        foreach (var entry in db.ChangeTracker.Entries().Where(e => e.State == EntityState.Added).ToList())
            entry.State = EntityState.Detached;

        analysis.Files = new();
        analysis.Status = MetricsAnalysisStatus.Failed;
        analysis.ErrorMessage = Truncate(error);
        analysis.CompletedAt = DateTime.UtcNow;
        await db.SaveChangesAsync();
    }

    private static string Truncate(string value) => value.Length > MaxErrorLength ? value[..MaxErrorLength] : value;
}
