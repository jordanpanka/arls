using System.Net.Http.Json;
using System.Text.Json;
using ef;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
public class ChatService
{
    private readonly CodeDbContext db;
    private readonly HttpClient httpClient;
    private readonly IConfiguration configuration;
    public ChatService(CodeDbContext cdb, HttpClient client, IConfiguration conf)
    {
        db = cdb;
        httpClient = client;
        configuration = conf;
    }
    public async Task<ServiceResult> AddConversationAsync(ConversationData data)
    {

        var exist = await db.Projects.AnyAsync(x => x.ID == data.projectId);
        if (!exist) return ServiceResult.Fail("Project doesn't exist");

        var conversation = new DbConversation
        {
            Title = data.title,
            ProjectID = data.projectId,
            CreatedAtUtc = DateTime.UtcNow,
            UpdatedAtUtc = DateTime.UtcNow
        };
        db.Conversations.Add(conversation);
        await db.SaveChangesAsync();
        int id = conversation.ID;
        return ServiceResult.Success(id);
        //Id return????????????????????????????????,

    }
    public async Task<ServiceResult> LoadConversationsAsync(ProjectID id)
    {
        var exist = await db.Projects.AnyAsync(x => x.ID == id.id);
        if (!exist) return ServiceResult.Fail("Project doesn't exist");

        var conv = await db.Conversations
        .Where(c => c.ProjectID == id.id)
        .Include(c => c.Messages)
        .Select(x => new Conversation
        {
            ID = x.ID,
            Title = x.Title,
            CreatedAtUtc = x.CreatedAtUtc,
            UpdatedAtUtc = x.UpdatedAtUtc,
            Messages = x.Messages
            .Select(m => new Message
            {
                ID = m.ID,
                Role = m.Role,
                Content = m.Content,
                CreatedAtUtc = m.CreatedAtUtc
            })
            .ToList()
        }).ToListAsync();

        return ServiceResult.Success(conv);
        /////nem jó az include még

    }
    public async Task<ServiceResult> DeleteConversationAsync(Id data)
    {
        var exist=await db.Conversations.SingleOrDefaultAsync(x=>x.ID==data.id);
        if(exist==null) return ServiceResult.Fail("Conversation doesn't exist");

        db.Conversations.Remove(exist);
        await db.SaveChangesAsync();
        return ServiceResult.Success();
    }

    public async Task<ServiceResult> RenameConversationAsync(RenameData data)
    {
        var exist=await db.Conversations.SingleOrDefaultAsync(x=>x.ID==data.id);
        if(exist==null) return ServiceResult.Fail("Conversation doesn't exist");

        exist.Title=data.name;
        await db.SaveChangesAsync();
        return ServiceResult.Success();
    }
    public async Task<ServiceResult> AddMessageAsync(MessageData data)
    {
        var exist = await db.Conversations.AnyAsync(x => x.ID == data.convId);
        if (!exist) return ServiceResult.Fail("The conversation doesn't exist.");

        var evidence = data.evidence is { ValueKind: JsonValueKind.Array } element ? element.GetRawText() : null;
        if (evidence != null && evidence.Length > MaxEvidenceLength) evidence = null;

        var message = new DbMessage
        {
            ConversationID = data.convId,
            Role = data.role,
            CreatedAtUtc = DateTime.UtcNow,
            Content = data.content,
            Evidence = evidence
        };
        db.Messages.Add(message);
        await db.SaveChangesAsync();
        return ServiceResult.Success();
    }

    public async Task<ServiceResult> LoadMessagesAsync(Id data)
    {
        var exist = await db.Conversations.AnyAsync(x => x.ID == data.id);
        if (!exist) return ServiceResult.Fail("The conversation doesn't exist.");

        var rows = await db.Messages
        .Where(x => x.ConversationID == data.id)
        .Select(m => new
        {
            m.ID,
            m.Role,
            m.CreatedAtUtc,
            m.Content,
            m.Evidence
        }).ToListAsync();

        var messages = rows.Select(m => new Message
        {
            ID = m.ID,
            Role = m.Role,
            CreatedAtUtc = m.CreatedAtUtc,
            Content = m.Content,
            Evidence = ParseStoredEvidence(m.Evidence)
        }).ToList();

        return ServiceResult.Success(messages);
    }
    private const int MaxEvidenceLength = 256 * 1024;

    private static JsonElement? ParseStoredEvidence(string? raw)
    {
        if (string.IsNullOrEmpty(raw)) return null;
        try
        {
            using var doc = JsonDocument.Parse(raw);
            return doc.RootElement.Clone();
        }
        catch (JsonException)
        {
            return null;
        }
    }

    private async Task<float[]> Embed(HttpClient http, string text)
    {

        var payload = new { model = configuration["AI:EmbedModel"], prompt = text };
        
        var response = await http.PostAsJsonAsync($"{configuration["AI:OllamaUrl"]}/api/embeddings", payload);
        response.EnsureSuccessStatusCode();
    
        using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        return doc.RootElement.GetProperty("embedding")
           .EnumerateArray()
           .Select(x => x.GetSingle())
           .ToArray();
    }
   /* public async Task<ServiceResult> SendMessageAsync(ChatRequest prompt)
    {
        Console.WriteLine(configuration["AI:EmbedModel"]);
        Console.WriteLine(configuration["AI:OllamaUrl"]);
        httpClient.Timeout = TimeSpan.FromMinutes(5);
        try
        {
            System.Console.WriteLine("Még jóóóóóóóóóó   000000");
            //text -> embedding
            var vec = await Embed(httpClient, prompt.prompt);

            System.Console.WriteLine(vec.Length);
            //Embedded text -> qdrant: search
            var searchPayload = new
            {
                vector = vec,
                limit = 3,
                with_payload = true

            };
            System.Console.WriteLine("Még jóóóóóóóóóó   000001");
            var response = await httpClient.PostAsJsonAsync($"{configuration["AI:QdrantUrl"]}/collections/{configuration["AI:Collection"]}/points/search", searchPayload);
            
            var content = await response.Content.ReadAsStringAsync();

            Console.WriteLine($"Status: {response.StatusCode}");
            Console.WriteLine(content);
            response.EnsureSuccessStatusCode();
            System.Console.WriteLine("Még jóóóóóóóóóó   000001");
            //
            using var searchDoc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
            var results = searchDoc.RootElement.GetProperty("result").EnumerateArray().ToList();
            System.Console.WriteLine("még jóóóó 1");
            //Have results or not
            if (results.Count == 0)
            {
                return ServiceResult.Success(new { answer = "Nem találom a dokumentumokban." });
            }

            //making context
            var contextParts = new List<string>();
            foreach (var r in results)
            {
                var payload = r.GetProperty("payload");
                var text = payload.GetProperty("text").GetString() ?? " ";
                var docName = payload.GetProperty("docName").GetString() ?? "doc";
                var idx = payload.GetProperty("chunkText").GetInt32();
                contextParts.Add($"[Forrás: {docName} #{idx}]\n{text}");
            }
            var context = string.Join("\n\n---\n\n", contextParts);
            System.Console.WriteLine("még jóóóó 2");
            // prompt to model
            var finalPrompt = $"""
            Te egy asszisztens vagy, aki KIZÁRÓLAG az alábbi KONTEKSZTUS alapján válaszol.Mindig azon a nyelven válaszolj, amilyen nyelven a kérdés elhangzott. A szavak közé tegyél szóközöket, ha kell, úgy higy értelmesen legyenek elválasztva.Ha a válasz nem található a kontextusban, mondd: "Nem találom a dokumentumokban."

            KONTEKSZTUS:
            {context}

            KÉRDÉS:
            {prompt.prompt}
            """;

            //Ollama generate
            var genPayload = new { model = configuration["AI:GenModel"], prompt = finalPrompt, stream = false };
            var genAnswer = await httpClient.PostAsJsonAsync($"{configuration["AI:OllamaUrl"]}/api/generate", genPayload);
            genAnswer.EnsureSuccessStatusCode();

            using var genDoc = JsonDocument.Parse(await genAnswer.Content.ReadAsStringAsync());

            var answer = genDoc.RootElement.GetProperty("response").GetString() ?? " ";

            Console.WriteLine("A válasz: " + answer);
            return ServiceResult.Success(new { answer });
        }
        catch (Exception e)
        {
            return ServiceResult.Fail(e.Message);
        }

    }*/
   public async Task<ServiceResult> SendMessageAsync(int userId,ChatRequest prompt)
{
    try
    {
        httpClient.Timeout = TimeSpan.FromMinutes(5);
        var pythonUrl = $"{configuration["AI:PythonUrl"]}/api/chat/files/send";

        var response = await httpClient.PostAsJsonAsync(pythonUrl,new ChatRequestPython(prompt.prompt,userId, prompt.investigationId,prompt.projectId));

        var responseBody = await response.Content.ReadAsStringAsync();

        if (!response.IsSuccessStatusCode)
        {
            return ServiceResult.Fail($"Python error: {responseBody}");
        }

        // JSON parse
        var json = JsonDocument.Parse(responseBody);
        var data = json.RootElement.GetProperty("data");

        var answer = data
                        .GetProperty("answer")
                        .GetString() ?? "";

        var evidence = data.TryGetProperty("evidence", out var evidenceElement)
            ? EvidenceJson.ParseList(evidenceElement)
            : new List<Evidence>();

        await AttachFileIdsAsync(prompt.projectId, evidence);

        return ServiceResult.Success(new ChatAnswer(answer, evidence));
    }
    catch (Exception ex)
    {
        return ServiceResult.Fail($"Chat failed: {ex.Message}");
    }
}

    // The AI service only knows repository paths; file IDs live in MSSQL.
    public async Task AttachFileIdsAsync(int projectId, List<Evidence> evidence)
    {
        var codeItems = evidence.OfType<CodeEvidence>().ToList();
        var graphNodes = evidence.OfType<GraphEvidence>().SelectMany(g => g.Nodes).Where(n => n.FilePath != null).ToList();

        var paths = codeItems.Select(c => EvidenceJson.NormalizePath(c.FilePath))
            .Concat(graphNodes.Select(n => EvidenceJson.NormalizePath(n.FilePath)))
            .Where(p => p != "")
            .Distinct()
            .ToList();

        if (paths.Count == 0) return;

        var ids = (await db.Files
                .Where(f => f.ProjectID == projectId && paths.Contains(f.RelativePath))
                .Select(f => new { f.ID, f.RelativePath })
                .ToListAsync())
            .GroupBy(f => f.RelativePath)
            .ToDictionary(g => g.Key, g => g.Min(f => f.ID).ToString());

        foreach (var item in codeItems)
        {
            item.FilePath = EvidenceJson.NormalizePath(item.FilePath);
            item.FileId = ids.GetValueOrDefault(item.FilePath);
        }

        foreach (var node in graphNodes)
        {
            node.FilePath = EvidenceJson.NormalizePath(node.FilePath);
            node.FileId = ids.GetValueOrDefault(node.FilePath);
        }
    }
}



