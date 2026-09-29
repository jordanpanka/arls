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