using System.Collections.Generic;
using System.ComponentModel.DataAnnotations.Schema;
using Microsoft.EntityFrameworkCore;

namespace ef
{
    [Table("Investigation")]
    public class DbInvestigation
    {
        [DatabaseGenerated(DatabaseGeneratedOption.Identity)]
        public int ID { get; set; }
        public int UserID {get; set;}
        public string Name { get; set; }
        public string Description { get; set; }
        public List<DbProject> Projects {get; set;}  

        [ForeignKey("UserID")]
        public DbUser User {get; set;}
    }

}