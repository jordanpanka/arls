using System.Text.Json;
using System.Text.Json.Serialization;

[JsonPolymorphic(TypeDiscriminatorPropertyName = "type")]
[JsonDerivedType(typeof(CodeEvidence), "code")]
[JsonDerivedType(typeof(GraphEvidence), "graph")]
[JsonDerivedType(typeof(MetricEvidence), "metric")]
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

public class MetricItem
{
    public string Key { get; set; } = "";
    public string Label { get; set; } = "";
    public double? Value { get; set; }
    public string? Unit { get; set; }
    public string? Category { get; set; }
}

// Values copied from a stored metrics analysis; the LLM only cites them.
public class MetricEvidence : Evidence
{
    public string Scope { get; set; } = "file";
    public string Title { get; set; } = "";
    public string? FileId { get; set; }
    public string? FileName { get; set; }
    public string? FilePath { get; set; }
    public string? Symbol { get; set; }
    public int? StartLine { get; set; }
    public int? EndLine { get; set; }
    public int? AnalysisId { get; set; }
    public string? AnalyzedAt { get; set; }
    public string? CommitSha { get; set; }
    public List<MetricItem> Items { get; set; } = new();
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
    // The files the AI service parses with Tree-sitter (CodeParser.code_parsers) and
    // analyzes with Lizard. Kept in one place on this side; a mismatch with Python
    // only makes the AI service report the file as skipped.
    public static readonly IReadOnlySet<string> CodeExtensions = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        ".py", ".cs", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs", ".php", ".c", ".h", ".cpp", ".hpp",
    };

    public static bool IsCode(string path) => CodeExtensions.Contains(Path.GetExtension(path));

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
