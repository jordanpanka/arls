using System;
using System.Collections.Generic;

public class MetricsOptions
{
    public MetricsThresholds Thresholds { get; set; } = new();
    public int StaticBatchSize { get; set; } = 100;
    public bool AutoAnalyzeAfterImport { get; set; } = true;
}

public class MetricsThresholds
{
    public int LowMax { get; set; } = 5;
    public int ModerateMax { get; set; } = 10;
    public int HighMax { get; set; } = 20;
    public int LongFunctionNloc { get; set; } = 50;
    public int ManyParameters { get; set; } = 5;
}

public static class ComplexityCategory
{
    public const string Low = "Low";
    public const string Moderate = "Moderate";
    public const string High = "High";
    public const string VeryHigh = "VeryHigh";
}

public record ComplexityBandDto(string Category, int Min, int? Max, string Label);

public record MetricsThresholdsDto(
    List<ComplexityBandDto> ComplexityBands,
    int HighComplexityAbove,
    int LongFunctionNloc,
    int ManyParameters);

public record MetricsAnalysisDto(
    int AnalysisId,
    int ProjectId,
    int? RepositoryId,
    string Status,
    string StaticStatus,
    string GraphStatus,
    string? ErrorMessage,
    string Trigger,
    string? Branch,
    string? CommitSha,
    DateTime CreatedAt,
    DateTime? StartedAt,
    DateTime? CompletedAt,
    double? TotalDurationMs,
    double? StaticDurationMs,
    double? GraphDurationMs,
    int FilesAnalyzed,
    int FilesSkipped,
    string StaticAnalyzer,
    string? GraphAnalyzer);

public record RepositorySummaryDto(
    int TotalFiles,
    int TotalNloc,
    int TotalFunctions,
    int? TotalClasses,
    double? AverageComplexity,
    int? MaxComplexity,
    string? MaxComplexityCategory,
    int HighComplexityFunctionCount,
    int LongFunctionCount,
    int ManyParameterFunctionCount,
    int? DependencyCount,
    int? CycleCount,
    double? AverageFanIn,
    double? AverageFanOut,
    int? MaxFanIn,
    int? MaxFanOut,
    int? MaxDependencyDepth,
    List<List<string>> Cycles);

public record DistributionBucketDto(string Category, string Label, int Count);

public record SkippedFileDto(string Path, string Reason);

public record RepositoryMetricsDto(
    MetricsAnalysisDto Analysis,
    RepositorySummaryDto Summary,
    List<DistributionBucketDto> ComplexityDistribution,
    MetricsThresholdsDto Thresholds,
    List<SkippedFileDto> SkippedFiles);

public record FileMetricDto(
    int Id,
    int? FileId,
    string Path,
    string Language,
    int Nloc,
    int TokenCount,
    int FunctionCount,
    int? ClassCount,
    double? AverageComplexity,
    int? MaxComplexity,
    string? ComplexityCategory,
    int HighComplexityFunctionCount,
    double? AverageFunctionNloc,
    int? MaxFunctionNloc,
    int LongFunctionCount,
    int ManyParameterFunctionCount,
    int? FanIn,
    int? FanOut,
    int? ImportCount);

public record FunctionMetricDto(
    int Id,
    int? FileId,
    string FilePath,
    string Name,
    string LongName,
    string? ClassName,
    int StartLine,
    int EndLine,
    int Nloc,
    int CyclomaticComplexity,
    string ComplexityCategory,
    int TokenCount,
    int ParameterCount,
    int Length,
    int? FanIn,
    int? FanOut,
    bool IsLong,
    bool HasManyParameters);

public record FileMetricsDetailDto(MetricsAnalysisDto Analysis, FileMetricDto File, List<FunctionMetricDto> Functions);

public record HotspotsDto(string Kind, List<FileMetricDto> Files, List<FunctionMetricDto> Functions);

public record MetricsStatusDto(MetricsAnalysisDto? Latest, MetricsAnalysisDto? LatestUsable);

public record AnalyzeMetricsRequest(bool force = false);

public record AnalyzeMetricsResponse(int AnalysisId, string Status, bool Reused);

public record MetricsSymbolRef(string path, string name, int? startLine);

public record RagMetricsRequest(
    int userId,
    int investigationId,
    List<string>? paths,
    List<MetricsSymbolRef>? symbols,
    bool includeRepository,
    string? focus,
    int? limit);

public record RagMetricsResponse(
    bool Available,
    MetricsAnalysisDto? Analysis,
    MetricsThresholdsDto? Thresholds,
    RepositorySummaryDto? Repository,
    List<FileMetricDto> Files,
    List<FunctionMetricDto> Functions,
    List<FileMetricDto> HotspotFiles,
    List<FunctionMetricDto> HotspotFunctions);

public enum MetricsLookupStatus { Found, ProjectNotFound, Forbidden, NoAnalysis, NotFound }

public record MetricsLookup<T>(MetricsLookupStatus Status, T? Data = default);

public record AiServiceResult<T>(
    [property: System.Text.Json.Serialization.JsonPropertyName("is_success")] bool IsSuccess,
    string? Message,
    T? Data);

public record AiFunctionMetrics(
    string Name,
    string LongName,
    string? ClassName,
    int StartLine,
    int EndLine,
    int Nloc,
    int CyclomaticComplexity,
    int TokenCount,
    int ParameterCount,
    int Length);

public record AiFileMetrics(string Path, string Language, int Nloc, int TokenCount, int? ClassCount, List<AiFunctionMetrics> Functions);

public record AiSkippedFile(string Path, string Reason);

public record AiStaticResult(string Analyzer, List<AiFileMetrics> Files, List<AiSkippedFile> Skipped, double DurationMs);

public record AiFileGraphMetrics(string Path, int FanIn, int FanOut, int ImportCount);

public record AiFunctionGraphMetrics(string Path, string Name, int? StartLine, int FanIn, int FanOut, int UnresolvedCalls);

public record AiGraphResult(
    string Analyzer,
    List<AiFileGraphMetrics> Files,
    List<AiFunctionGraphMetrics> Functions,
    int DependencyCount,
    int CycleCount,
    List<List<string>> Cycles,
    int MaxDependencyDepth,
    int AmbiguousCalls,
    int UnresolvedCalls,
    double DurationMs);
