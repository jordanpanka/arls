using DocumentFormat.OpenXml.Presentation;
using Microsoft.Identity.Client;

public class File
{
    public int ID { get; set; }
    public string Name { get; set; }
    public string RelativePath { get; set; }
    public string StoragePath { get; set; }
    public string Extension { get; set; }
    public string ContentType { get; set; } = "";
    public long Size { get; set; }

}