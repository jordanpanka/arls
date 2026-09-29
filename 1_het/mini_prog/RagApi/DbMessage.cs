using System;
using System.ComponentModel.DataAnnotations.Schema;

namespace ef
{
    [Table("Message")]
    public class DbMessage
    {
        [DatabaseGenerated(DatabaseGeneratedOption.Identity)]
        public int ID {get; set;}
        public int ConversationID {get; set;}
        public string Role {get; set;}
        public DateTime CreatedAtUtc{ get; set;}

        public string Content {get; set;}

        [ForeignKey("ConversationID")]
        public DbConversation Conversation{get; set;}
    }
}