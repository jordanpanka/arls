using System.ComponentModel.DataAnnotations.Schema;

namespace ef
{
    [Table("File")]
    public class DbFile
    {
        [DatabaseGenerated(DatabaseGeneratedOption.Identity)]
        public int ID { get; set; }
        public int ProjectID { get; set; }
        public string Name { get; set; }
        public string RelativePath { get; set; }
        public string StoragePath { get; set; }
        public string Extension { get; set; } 
        public string ContentType { get; set; } = "";
        public long Size { get; set; }

        [ForeignKey("ProjectID")]
        public DbProject Project {get; set;}

    }
}