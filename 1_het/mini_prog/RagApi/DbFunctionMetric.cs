using System.ComponentModel.DataAnnotations.Schema;

namespace ef
{
    [Table("FunctionMetric")]
    public class DbFunctionMetric
    {
        [DatabaseGenerated(DatabaseGeneratedOption.Identity)]
        public int ID { get; set; }
        public int FileMetricID { get; set; }

        public string Name { get; set; } = "";
        public string LongName { get; set; } = "";
        public string? ClassName { get; set; }
        public int StartLine { get; set; }
        public int EndLine { get; set; }

        public int Nloc { get; set; }
        public int CyclomaticComplexity { get; set; }
        public int TokenCount { get; set; }
        public int ParameterCount { get; set; }
        public int Length { get; set; }

        public int? FanIn { get; set; }
        public int? FanOut { get; set; }

        [ForeignKey("FileMetricID")]
        public DbFileMetric FileMetric { get; set; } = null!;
    }
}
