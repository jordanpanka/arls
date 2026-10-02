using ef;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using System.Net;
using System.Text;
using Xunit;

public class ChatServiceTests
{
    private CodeDbContext CreateDb()
    {
        var options = new DbContextOptionsBuilder<CodeDbContext>()
            .UseInMemoryDatabase(Guid.NewGuid().ToString())
            .Options;

        return new CodeDbContext(options);
    }

    private IConfiguration CreateConfig()
    {
        return new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["AI:PythonUrl"] = "http://test-python"
            })
            .Build();
    }

    private HttpClient CreateHttpClient(string responseBody, HttpStatusCode statusCode = HttpStatusCode.OK)
    {
        var handler = new FakeHttpMessageHandler(responseBody, statusCode);
        return new HttpClient(handler);
    }

    [Fact]
    public async Task AddConversationAsync_ShouldCreateConversation_WhenProjectExists()
    {
        var db = CreateDb();

        db.Projects.Add(new DbProject
        {
            ID = 1,
            Name = "Test Project",
            Description = "Desc",
            InvestigationID = 1
        });

        await db.SaveChangesAsync();

        var service = new ChatService(db, CreateHttpClient("{}"), CreateConfig());

        var data = new ConversationData(1, "Test conversation");

        var result = await service.AddConversationAsync(data);

        Assert.True(result.Ok);

        var conversation = await db.Conversations.FirstOrDefaultAsync();

        Assert.NotNull(conversation);
        Assert.Equal("Test conversation", conversation.Title);
        Assert.Equal(1, conversation.ProjectID);
    }

    [Fact]
    public async Task AddConversationAsync_ShouldFail_WhenProjectDoesNotExist()
    {
        var db = CreateDb();

        var service = new ChatService(db, CreateHttpClient("{}"), CreateConfig());

        var data = new ConversationData(999, "Test conversation");

        var result = await service.AddConversationAsync(data);

        Assert.False(result.Ok);
        Assert.Equal("Project doesn't exist", result.Error);
    }

    [Fact]
    public async Task AddMessageAsync_ShouldCreateMessage_WhenConversationExists()
    {
        var db = CreateDb();

        db.Conversations.Add(new DbConversation
        {
            ID = 1,
            Title = "Conversation",
            ProjectID = 1,
            CreatedAtUtc = DateTime.UtcNow,
            UpdatedAtUtc = DateTime.UtcNow
        });

        await db.SaveChangesAsync();

        var service = new ChatService(db, CreateHttpClient("{}"), CreateConfig());

        var data = new MessageData(1, "Hello", "user");

        var result = await service.AddMessageAsync(data);

        Assert.True(result.Ok);

        var message = await db.Messages.FirstOrDefaultAsync();

        Assert.NotNull(message);
        Assert.Equal(1, message.ConversationID);
        Assert.Equal("user", message.Role);
        Assert.Equal("Hello", message.Content);
    }

    [Fact]
    public async Task RenameConversationAsync_ShouldRenameConversation_WhenConversationExists()
    {
        var db = CreateDb();

        db.Conversations.Add(new DbConversation
        {
            ID = 1,
            Title = "Old title",
            ProjectID = 1,
            CreatedAtUtc = DateTime.UtcNow,
            UpdatedAtUtc = DateTime.UtcNow
        });

        await db.SaveChangesAsync();

        var service = new ChatService(db, CreateHttpClient("{}"), CreateConfig());

        var result = await service.RenameConversationAsync(new RenameData(1, "New title"));

        Assert.True(result.Ok);

        var conversation = await db.Conversations.FirstAsync(x => x.ID == 1);

        Assert.Equal("New title", conversation.Title);
    }

    [Fact]
    public async Task DeleteConversationAsync_ShouldDeleteConversation_WhenConversationExists()
    {
        var db = CreateDb();

        db.Conversations.Add(new DbConversation
        {
            ID = 1,
            Title = "Conversation",
            ProjectID = 1,
            CreatedAtUtc = DateTime.UtcNow,
            UpdatedAtUtc = DateTime.UtcNow
        });

        await db.SaveChangesAsync();

        var service = new ChatService(db, CreateHttpClient("{}"), CreateConfig());

        var result = await service.DeleteConversationAsync(new Id(1));

        Assert.True(result.Ok);
        Assert.Empty(db.Conversations);
    }

    [Fact]
    public async Task SendMessageAsync_ShouldReturnAnswer_WhenPythonApiReturnsSuccess()
    {
        var db = CreateDb();

        var json = """
        {
            "data": {
                "answer": "Teszt válasz"
            }
        }
        """;

        var service = new ChatService(db, CreateHttpClient(json), CreateConfig());

        var result = await service.SendMessageAsync(1, new ChatRequest("Mi ez?", 1,1));

        Assert.True(result.Ok);
    }

    [Fact]
    public async Task SendMessageAsync_ShouldReturnEvidence_WithResolvedFileIds()
    {
        var db = CreateDb();
        db.Files.AddRange(
            new DbFile { ID = 7, ProjectID = 1, Name = "UserService.cs", RelativePath = "src/UserService.cs", StoragePath = "", Extension = ".cs" },
            new DbFile { ID = 8, ProjectID = 2, Name = "UserService.cs", RelativePath = "src/UserService.cs", StoragePath = "", Extension = ".cs" });
        await db.SaveChangesAsync();

        var json = """
        {
            "data": {
                "answer": "It delegates [SOURCE_1].",
                "evidence": [
                    {
                        "type": "code", "id": "SOURCE_1", "fileId": null,
                        "fileName": "UserService.cs", "filePath": "src\\UserService.cs", "language": "csharp",
                        "highlights": [ { "startLine": 42, "endLine": 55 } ],
                        "retrievalType": "code", "score": 0.8
                    },
                    {
                        "id": "GRAPH_1", "type": "graph",
                        "nodes": [
                            { "id": "n1", "label": "GetUser", "type": "Function", "filePath": "/src/UserService.cs", "startLine": 42, "endLine": 55, "usedAsEvidence": true },
                            { "id": "n2", "label": "Missing", "type": "Function", "filePath": "src/Gone.cs" },
                            { "id": "n3", "label": "log", "type": "Function" }
                        ],
                        "edges": [ { "source": "n1", "target": "n3", "type": "CALLS" } ]
                    },
                    { "type": "unknown", "id": "X" }
                ]
            }
        }
        """;

        var service = new ChatService(db, CreateHttpClient(json), CreateConfig());

        var result = await service.SendMessageAsync(1, new ChatRequest("Mi ez?", 1, 1));

        Assert.True(result.Ok);
        var answer = Assert.IsType<ChatAnswer>(result.Data);
        Assert.Equal(2, answer.Evidence.Count);

        var code = Assert.IsType<CodeEvidence>(answer.Evidence[0]);
        Assert.Equal("7", code.FileId);
        Assert.Equal("src/UserService.cs", code.FilePath);
        Assert.Equal(new Highlight(42, 55), Assert.Single(code.Highlights));

        var graph = Assert.IsType<GraphEvidence>(answer.Evidence[1]);
        Assert.Equal("7", graph.Nodes[0].FileId);
        Assert.Null(graph.Nodes[1].FileId);
        Assert.Null(graph.Nodes[2].FileId);
        Assert.Single(graph.Edges);

        var serialized = System.Text.Json.JsonSerializer.Serialize(answer, EvidenceJson.Options);
        Assert.Contains("\"type\":\"code\"", serialized);
        Assert.Contains("\"type\":\"graph\"", serialized);
        Assert.Contains("\"fileId\":\"7\"", serialized);
    }

    [Fact]
    public async Task SendMessageAsync_ShouldReturnEmptyEvidence_WhenPythonOmitsIt()
    {
        var service = new ChatService(CreateDb(), CreateHttpClient("""{ "data": { "answer": "ok" } }"""), CreateConfig());

        var result = await service.SendMessageAsync(1, new ChatRequest("?", 1, 1));

        var answer = Assert.IsType<ChatAnswer>(result.Data);
        Assert.Equal("ok", answer.Answer);
        Assert.Empty(answer.Evidence);
    }

    [Fact]
    public async Task Messages_ShouldRoundTripEvidence()
    {
        var db = CreateDb();
        db.Conversations.Add(new DbConversation { ID = 1, Title = "c", ProjectID = 1, CreatedAtUtc = DateTime.UtcNow, UpdatedAtUtc = DateTime.UtcNow });
        await db.SaveChangesAsync();
        var service = new ChatService(db, CreateHttpClient("{}"), CreateConfig());

        using var evidence = System.Text.Json.JsonDocument.Parse("""[{"type":"code","id":"SOURCE_1"}]""");
        await service.AddMessageAsync(new MessageData(1, "answer", "AI", evidence.RootElement.Clone()));
        await service.AddMessageAsync(new MessageData(1, "question", "User"));

        var result = await service.LoadMessagesAsync(new Id(1));

        var messages = Assert.IsType<List<Message>>(result.Data);
        Assert.Equal("SOURCE_1", messages[0].Evidence!.Value[0].GetProperty("id").GetString());
        Assert.Null(messages[1].Evidence);
    }

    [Fact]
    public async Task SendMessageAsync_ShouldFail_WhenPythonApiReturnsError()
    {
        var db = CreateDb();

        var service = new ChatService(
            db,
            CreateHttpClient("Python hiba", HttpStatusCode.InternalServerError),
            CreateConfig()
        );

        var result = await service.SendMessageAsync(1,new ChatRequest("Mi ez?",1, 1));

        Assert.False(result.Ok);
    }
}

public class FakeHttpMessageHandler : HttpMessageHandler
{
    private readonly string responseBody;
    private readonly HttpStatusCode statusCode;

    public FakeHttpMessageHandler(string responseBody, HttpStatusCode statusCode)
    {
        this.responseBody = responseBody;
        this.statusCode = statusCode;
    }

    protected override Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request,
        CancellationToken cancellationToken)
    {
        var response = new HttpResponseMessage(statusCode)
        {
            Content = new StringContent(responseBody, Encoding.UTF8, "application/json")
        };

        return Task.FromResult(response);
    }
}