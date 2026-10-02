using System.Text.Json;
using System.Text.Json.Serialization;

[JsonPolymorphic(TypeDiscriminatorPropertyName = "type")]
[JsonDerivedType(typeof(CodeEvidence), "code")]
[JsonDerivedType(typeof(GraphEvidence), "graph")]
public abstract class Evidence
{
    public string Id { get; set; } = "";
}

public record Highlight(int StartLine, int EndLine);

public class CodeEvidence : Evidence
{
    public string? FileId { get; set; }
    public string FileName { get; set; } = "";
    public string FilePath { get; set; } = "";
    public string Language { get; set; } = "plaintext";
    public List<Highlight> Highlights { get; set; } = new();
    public List<string> Symbols { get; set; } = new();
    public string? RetrievalType { get; set; }
    public double? Score { get; set; }
}

public class GraphNode
{
    public string Id { get; set; } = "";
    public string Label { get; set; } = "";
    public string Type { get; set; } = "";
    public string? FileId { get; set; }
    public string? FilePath { get; set; }
    public int? StartLine { get; set; }
    public int? EndLine { get; set; }
    public bool UsedAsEvidence { get; set; }
}

public class GraphEdge
{
    public string Source { get; set; } = "";
    public string Target { get; set; } = "";
    public string Type { get; set; } = "";
}

public class GraphEvidence : Evidence
{
    public List<GraphNode> Nodes { get; set; } = new();
    public List<GraphEdge> Edges { get; set; } = new();
}

public record ChatAnswer(string Answer, List<Evidence> Evidence);

public record ProjectFileContent(string FileId, string FileName, string FilePath, string Language, string Content);

public static class EvidenceJson
{
    public static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web)
    {
        AllowOutOfOrderMetadataProperties = true
    };

    public static string NormalizePath(string? path)
    {
        var normalized = (path ?? "").Replace("\\", "/").Trim();
        return normalized.TrimStart('/');
    }

    // One malformed item must not cost the user the answer or the other items.
    public static List<Evidence> ParseList(JsonElement element)
    {
        var items = new List<Evidence>();
        if (element.ValueKind != JsonValueKind.Array) return items;

        foreach (var item in element.EnumerateArray())
        {
            try
            {
                var parsed = item.Deserialize<Evidence>(Options);
                if (parsed != null) items.Add(parsed);
            }
            catch (Exception ex) when (ex is JsonException or NotSupportedException)
            {
            }
        }
        return items;
    }
}

public static class SourceLanguage
{
    private static readonly Dictionary<string, string> ByExtension = new(StringComparer.OrdinalIgnoreCase)
    {
        [".py"] = "python", [".cs"] = "csharp", [".js"] = "javascript", [".jsx"] = "javascript",
        [".ts"] = "typescript", [".tsx"] = "typescript", [".java"] = "java", [".go"] = "go",
        [".rs"] = "rust", [".php"] = "php", [".c"] = "c", [".h"] = "cpp", [".cpp"] = "cpp",
        [".hpp"] = "cpp", [".json"] = "json", [".yaml"] = "yaml", [".yml"] = "yaml",
        [".xml"] = "xml", [".toml"] = "ini", [".ini"] = "ini", [".cfg"] = "ini", [".conf"] = "ini",
        [".properties"] = "ini", [".sql"] = "sql", [".md"] = "markdown", [".html"] = "html",
        [".css"] = "css",
    };

    public static string FromPath(string path)
    {
        var name = Path.GetFileName(path).ToLowerInvariant();
        if (name is "dockerfile" or "containerfile") return "dockerfile";
        if (name == "makefile") return "shell";
        return ByExtension.TryGetValue(Path.GetExtension(name), out var language) ? language : "plaintext";
    }
}
