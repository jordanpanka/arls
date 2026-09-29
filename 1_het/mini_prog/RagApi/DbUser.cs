using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Internal;
using System.ComponentModel.DataAnnotations.Schema;
namespace ef
{
    [Table("User")]
    public class DbUser
    {
         [DatabaseGenerated(DatabaseGeneratedOption.Identity)]
        public int ID { get; set; }
        public string Email { get; set; }
        public string FirstName {get; set;}
        public string LastName {get; set;}
        public byte[]  PasswordHash { get; set; }
        public byte[] Passwordsalt { get; set; }
        public DateTime CreatedTime { get; set; }
        public List<DbInvestigation> Investigations {get; set;}

    }

}