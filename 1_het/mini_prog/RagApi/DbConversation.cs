using System;
using System.Collections.Generic;
using System.ComponentModel.DataAnnotations.Schema;

namespace ef
{
    [Table("Conversation")]
    public class DbConversation
    {
        [DatabaseGenerated(DatabaseGeneratedOption.Identity)]
        public int ID {get; set;}

        public int ProjectID {get; set;}

        public string Title {get; set;}

        public DateTime CreatedAtUtc {get; set;}

        public DateTime UpdatedAtUtc{get; set;}
        public List<DbMessage> Messages {get; set;}
        
        [ForeignKey("ProjectID")]
        public DbProject Project {get; set;}


    }
}