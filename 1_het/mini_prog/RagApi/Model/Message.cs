public class Message
{
    public int ID { get; set; }
    public int ConversationID { get; set; }
    public string Role { get; set; }
    public DateTime CreatedAtUtc { get; set; }

    public string Content {get; set;}
}