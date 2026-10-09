using System.Collections.Generic;
using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace ef
{
    [Table("FileMetric")]
    public class DbFileMetric
    {
        [DatabaseGenerated(DatabaseGeneratedOption.Identity)]
        public int ID { get; set; }
        public int AnalysisID { get; set; }

        // Resolved from File.RelativePath when the run was stored; no foreign key,
        // so deleting a file never touches historical metrics.
        public int? FileID { get; set; }

        [MaxLength(450)]
        public string Path { get; set; } = "";
        public string Language { get; set; } = "";

        public int Nloc { get; set; }
        public int TokenCount { get; set; }
        public int FunctionCount { get; set; }
        public int? ClassCount { get; set; }

        // Null when the file has no functions: there is nothing to average.
        public double? AverageComplexity { get; set; }
        public int? MaxComplexity { get; set; }
        public int HighComplexityFunctionCount { get; set; }
        public double? AverageFunctionNloc { get; set; }
        public int? MaxFunctionNloc { get; set; }
        public int LongFunctionCount { get; set; }
        public int ManyParameterFunctionCount { get; set; }

        public int? FanIn { get; set; }
        public int? FanOut { get; set; }
        public int? ImportCount { get; set; }

        [ForeignKey("AnalysisID")]
        public DbMetricsAnalysis Analysis { get; set; } = null!;

        public List<DbFunctionMetric> Functions { get; set; } = new();
    }
}
