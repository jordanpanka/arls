public class Conversation
{
    public int ID { get; set; }
    public string Title { get; set; }

    public DateTime CreatedAtUtc { get; set; }

    public DateTime UpdatedAtUtc { get; set; }
    public List<Message> Messages { get; set; }

}