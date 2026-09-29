using System.Collections.Generic;
using System.ComponentModel.DataAnnotations.Schema;

namespace ef
{
    [Table("Project")]
    public class DbProject
    {
        [DatabaseGenerated(DatabaseGeneratedOption.Identity)]
        public int ID { get; set; }
        public int InvestigationID {get; set;}
        public string Name { get; set;}
        public string Description {get; set;}
        public List<DbFile> Files {get; set;}
        public List<DbConversation> Conversations {get; set;}
        public List<DbRepository> Repositories {get; set;}

        [ForeignKey("InvestigationID")]
        public DbInvestigation Investigation {get; set;}

    }
}