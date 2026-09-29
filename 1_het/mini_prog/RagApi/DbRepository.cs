using System;
using System.ComponentModel.DataAnnotations.Schema;

namespace ef
{
    [Table("Repository")]
    public class DbRepository
    {
        [DatabaseGenerated(DatabaseGeneratedOption.Identity)]
        public int ID { get; set; }
        public int ProjectID { get; set; }

        public string Owner { get; set; } = "";
        public string Name { get; set; } = "";


        public string Reference { get; set; } = "";

        public string CommitSha { get; set; } = "";

        public string Status { get; set; } = RepositoryStatus.Pending;
        public string? ErrorMessage { get; set; }

        public int IndexedFileCount { get; set; }

        public int SkippedFileCount { get; set; }

        public int TotalFileCount { get; set; }

        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
        public DateTime? IndexedAt { get; set; }

        [ForeignKey("ProjectID")]
        public DbProject Project { get; set; }
    }

    public static class RepositoryStatus
    {
        public const string Pending = "Pending";

        public const string Queued = "Queued";
        public const string Fetching = "Fetching";
        public const string Indexing = "Indexing";
        public const string Ready = "Ready";
        public const string Failed = "Failed";

        public static readonly string[] InFlight = { Pending, Queued, Fetching, Indexing };
    }
}
