using System;
using System.Collections.Generic;
using System.Linq;
using ef;

public static class MetricsAggregator
{
    public static string Categorize(int complexity, MetricsThresholds t) =>
        complexity <= t.LowMax ? ComplexityCategory.Low
        : complexity <= t.ModerateMax ? ComplexityCategory.Moderate
        : complexity <= t.HighMax ? ComplexityCategory.High
        : ComplexityCategory.VeryHigh;

    public static bool IsHighComplexity(int complexity, MetricsThresholds t) => complexity > t.ModerateMax;

    public static bool IsLong(int nloc, MetricsThresholds t) => nloc > t.LongFunctionNloc;

    public static bool HasManyParameters(int parameterCount, MetricsThresholds t) => parameterCount > t.ManyParameters;

    public static List<ComplexityBandDto> Bands(MetricsThresholds t) => new()
    {
        new(ComplexityCategory.Low, 1, t.LowMax, $"1–{t.LowMax}"),
        new(ComplexityCategory.Moderate, t.LowMax + 1, t.ModerateMax, $"{t.LowMax + 1}–{t.ModerateMax}"),
        new(ComplexityCategory.High, t.ModerateMax + 1, t.HighMax, $"{t.ModerateMax + 1}–{t.HighMax}"),
        new(ComplexityCategory.VeryHigh, t.HighMax + 1, null, $"{t.HighMax + 1}+"),
    };

    public static MetricsThresholdsDto ToDto(MetricsThresholds t) =>
        new(Bands(t), t.ModerateMax, t.LongFunctionNloc, t.ManyParameters);

    public static List<DistributionBucketDto> Distribution(IEnumerable<int> complexities, MetricsThresholds t)
    {
        var counts = complexities
            .GroupBy(c => Categorize(c, t))
            .ToDictionary(g => g.Key, g => g.Count());

        return Bands(t)
            .Select(b => new DistributionBucketDto(b.Category, b.Label, counts.GetValueOrDefault(b.Category)))
            .ToList();
    }

    public static DbFileMetric BuildFile(AiFileMetrics file, MetricsThresholds t)
    {
        var functions = file.Functions.Select(f => new DbFunctionMetric
        {
            Name = f.Name,
            LongName = f.LongName,
            ClassName = string.IsNullOrWhiteSpace(f.ClassName) ? null : f.ClassName,
            StartLine = f.StartLine,
            EndLine = f.EndLine,
            Nloc = f.Nloc,
            CyclomaticComplexity = f.CyclomaticComplexity,
            TokenCount = f.TokenCount,
            ParameterCount = f.ParameterCount,
            Length = f.Length,
        }).ToList();

        var any = functions.Count > 0;

        return new DbFileMetric
        {
            Path = EvidenceJson.NormalizePath(file.Path),
            Language = file.Language,
            Nloc = file.Nloc,
            TokenCount = file.TokenCount,
            FunctionCount = functions.Count,
            ClassCount = file.ClassCount,
            AverageComplexity = any ? functions.Average(f => f.CyclomaticComplexity) : null,
            MaxComplexity = any ? functions.Max(f => f.CyclomaticComplexity) : null,
            HighComplexityFunctionCount = functions.Count(f => IsHighComplexity(f.CyclomaticComplexity, t)),
            AverageFunctionNloc = any ? functions.Average(f => f.Nloc) : null,
            MaxFunctionNloc = any ? functions.Max(f => f.Nloc) : null,
            LongFunctionCount = functions.Count(f => IsLong(f.Nloc, t)),
            ManyParameterFunctionCount = functions.Count(f => HasManyParameters(f.ParameterCount, t)),
            Functions = functions,
        };
    }

    public static string ShortName(string? name)
    {
        var value = name ?? "";
        foreach (var separator in new[] { "::", "->", "." })
        {
            var index = value.LastIndexOf(separator, StringComparison.Ordinal);
            if (index >= 0) value = value[(index + separator.Length)..];
        }
        return value.Trim();
    }

    public static void ApplyGraph(IEnumerable<DbFileMetric> files, AiGraphResult graph)
    {
        var fileGraph = graph.Files
            .GroupBy(f => EvidenceJson.NormalizePath(f.Path))
            .ToDictionary(g => g.Key, g => g.First());

        var functionGraph = graph.Functions
            .GroupBy(f => (EvidenceJson.NormalizePath(f.Path), ShortName(f.Name)))
            .ToDictionary(g => g.Key, g => g.First());

        foreach (var file in files)
        {
            if (fileGraph.TryGetValue(file.Path, out var g))
            {
                file.FanIn = g.FanIn;
                file.FanOut = g.FanOut;
                file.ImportCount = g.ImportCount;
            }

            foreach (var function in file.Functions)
            {
                if (functionGraph.TryGetValue((file.Path, ShortName(function.Name)), out var fg))
                {
                    function.FanIn = fg.FanIn;
                    function.FanOut = fg.FanOut;
                }
            }
        }
    }

    public static void ApplyRepository(DbMetricsAnalysis analysis, IReadOnlyCollection<DbFileMetric> files, AiGraphResult? graph, MetricsThresholds t)
    {
        var functions = files.SelectMany(f => f.Functions).ToList();
        var classCounts = files.Where(f => f.ClassCount.HasValue).Select(f => f.ClassCount!.Value).ToList();

        analysis.FilesAnalyzed = files.Count;
        analysis.TotalNloc = files.Sum(f => f.Nloc);
        analysis.TotalFunctions = functions.Count;
        analysis.TotalClasses = classCounts.Count > 0 ? classCounts.Sum() : null;
        analysis.AverageComplexity = functions.Count > 0 ? functions.Average(f => f.CyclomaticComplexity) : null;
        analysis.MaxComplexity = functions.Count > 0 ? functions.Max(f => f.CyclomaticComplexity) : null;
        analysis.HighComplexityFunctionCount = functions.Count(f => IsHighComplexity(f.CyclomaticComplexity, t));
        analysis.LongFunctionCount = functions.Count(f => IsLong(f.Nloc, t));
        analysis.ManyParameterFunctionCount = functions.Count(f => HasManyParameters(f.ParameterCount, t));

        if (graph == null) return;

        var connected = files.Where(f => f.FanIn.HasValue).ToList();
        analysis.DependencyCount = graph.DependencyCount;
        analysis.CycleCount = graph.CycleCount;
        analysis.MaxDependencyDepth = graph.MaxDependencyDepth;
        analysis.AverageFanIn = connected.Count > 0 ? connected.Average(f => f.FanIn!.Value) : null;
        analysis.AverageFanOut = connected.Count > 0 ? connected.Average(f => f.FanOut!.Value) : null;
        analysis.MaxFanIn = connected.Count > 0 ? connected.Max(f => f.FanIn!.Value) : null;
        analysis.MaxFanOut = connected.Count > 0 ? connected.Max(f => f.FanOut!.Value) : null;
    }

    public static int MaintainabilityIndicatorCount(DbFileMetric f) =>
        f.HighComplexityFunctionCount + f.LongFunctionCount + f.ManyParameterFunctionCount;
}
