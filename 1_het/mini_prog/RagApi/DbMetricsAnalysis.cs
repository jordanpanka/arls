using System;
using System.Collections.Generic;
using System.ComponentModel.DataAnnotations.Schema;

namespace ef
{
    
    [Table("MetricsAnalysis")]
    public class DbMetricsAnalysis
    {
        [DatabaseGenerated(DatabaseGeneratedOption.Identity)]
        public int ID { get; set; }
        public int ProjectID { get; set; }

        // Plain column, not a foreign key: Project already cascades to both
        // tables, and SQL Server rejects a second cascade path.
        public int? RepositoryID { get; set; }

        public string Status { get; set; } = MetricsAnalysisStatus.Queued;
        public string StaticStatus { get; set; } = MetricsPhaseStatus.Pending;
        public string GraphStatus { get; set; } = MetricsPhaseStatus.Pending;
        public string? ErrorMessage { get; set; }
        public string Trigger { get; set; } = MetricsTrigger.Manual;

        public string? Branch { get; set; }
        public string? CommitSha { get; set; }
        // Hash of the analyzed code files (path + size): lets an unchanged project reuse its last run.
        public string? FileSetHash { get; set; }
        public string StaticAnalyzer { get; set; } = "";
        public string? GraphAnalyzer { get; set; }

        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
        public DateTime? StartedAt { get; set; }
        public DateTime? CompletedAt { get; set; }

        public double? TotalDurationMs { get; set; }
        public double? StaticDurationMs { get; set; }
        public double? GraphDurationMs { get; set; }
        public int FilesAnalyzed { get; set; }
        public int FilesSkipped { get; set; }
        public string? SkippedFilesJson { get; set; }

        public int TotalNloc { get; set; }
        public int TotalFunctions { get; set; }
        public int? TotalClasses { get; set; }
        public double? AverageComplexity { get; set; }
        public int? MaxComplexity { get; set; }
        public int HighComplexityFunctionCount { get; set; }
        public int LongFunctionCount { get; set; }
        public int ManyParameterFunctionCount { get; set; }

        // Null when the graph phase failed or did not run.
        public int? DependencyCount { get; set; }
        public int? CycleCount { get; set; }
        public double? AverageFanIn { get; set; }
        public double? AverageFanOut { get; set; }
        public int? MaxFanIn { get; set; }
        public int? MaxFanOut { get; set; }
        public int? MaxDependencyDepth { get; set; }
        public string? CyclesJson { get; set; }

        public string ThresholdsJson { get; set; } = "";

        [ForeignKey("ProjectID")]
        public DbProject Project { get; set; } = null!;

        public List<DbFileMetric> Files { get; set; } = new();
    }

    public static class MetricsAnalysisStatus
    {
        public const string Queued = "Queued";
        public const string Running = "Running";
        public const string Completed = "Completed";
        // Static metrics stored, graph metrics missing.
        public const string Partial = "Partial";
        public const string Failed = "Failed";

        public static readonly string[] InFlight = { Queued, Running };
        public static readonly string[] Usable = { Completed, Partial };
    }

    public static class MetricsPhaseStatus
    {
        public const string Pending = "Pending";
        public const string Completed = "Completed";
        public const string Failed = "Failed";
    }

    public static class MetricsTrigger
    {
        public const string Manual = "Manual";
        public const string Import = "Import";
    }
}
