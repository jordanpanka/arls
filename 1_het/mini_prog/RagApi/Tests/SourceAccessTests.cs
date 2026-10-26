using System.Net;
using System.Text;
using System.Text.Json;
using ef;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Configuration;
using Xunit;

public class SourceAccessServiceTests
{
    private const string ServicePath = "users/10/investigations/1/projects/100/original/src/Services/PaymentService.cs";

    private static async Task<(SourceAccessService Service, FakeMinioService Minio)> CreateAsync()
    {
        var db = await MetricsServiceTests.SeedProjectsAsync(MetricsServiceTests.CreateDb());
        db.Files.AddRange(
            new DbFile { ID = 1, ProjectID = 100, Name = "PaymentService.cs", RelativePath = "src/Services/PaymentService.cs", StoragePath = "", Extension = ".cs", Size = 120 },
            new DbFile { ID = 2, ProjectID = 100, Name = "Api.cs", RelativePath = "src/Api/Api.cs", StoragePath = "", Extension = ".cs", Size = 40 },
            new DbFile { ID = 3, ProjectID = 100, Name = "README.md", RelativePath = "README.md", StoragePath = "", Extension = ".md", Size = 10 },
            new DbFile { ID = 4, ProjectID = 200, Name = "Secret.cs", RelativePath = "src/Secret.cs", StoragePath = "", Extension = ".cs", Size = 10 });
        db.Repositories.Add(new DbRepository { ID = 1, ProjectID = 100, Status = RepositoryStatus.Ready, CommitSha = "abc123", IndexedAt = DateTime.UtcNow });
        await db.SaveChangesAsync();

        var minio = new FakeMinioService();
        minio.Objects[ServicePath] = Encoding.UTF8.GetBytes("class PaymentService\r\n{\r\n  void Process() { Charge(); }\r\n  void Charge() { }\r\n}");
        minio.Objects["users/10/investigations/1/projects/100/original/src/Api/Api.cs"] = Encoding.UTF8.GetBytes("class Api { void Pay() { new PaymentService().Process(); } }");
        return (new SourceAccessService(db, minio), minio);
    }

    [Fact]
    public async Task Files_ReturnsSnapshotIdentity()
    {
        var (service, _) = await CreateAsync();

        var result = await service.FilesAsync(100, new SourceFilesRequest(10, 1, includeFiles: true));

        Assert.Equal(SourceLookupStatus.Found, result.Status);
        Assert.Equal("abc123", result.Data!.CommitSha);
        Assert.Equal(64, result.Data.FileSetHash.Length);
        Assert.Equal(3, result.Data.FileCount);
        Assert.Contains(result.Data.Files!, f => f.Path == "README.md");
    }

    [Theory]
    [InlineData(20, 1)]
    [InlineData(10, 2)]
    public async Task EveryEndpoint_RejectsOtherOwnersOrInvestigations(int userId, int investigationId)
    {
        var (service, minio) = await CreateAsync();

        Assert.Equal(SourceLookupStatus.Forbidden, (await service.FilesAsync(100, new SourceFilesRequest(userId, investigationId))).Status);
        Assert.Equal(SourceLookupStatus.Forbidden, (await service.ContentAsync(100, new SourceContentRequest(userId, investigationId, "src/Services/PaymentService.cs"))).Status);
        Assert.Equal(SourceLookupStatus.Forbidden, (await service.SearchAsync(100, new SourceSearchRequest(userId, investigationId, "Payment"))).Status);
        Assert.Empty(minio.Requested);
    }

    [Theory]
    [InlineData("../other/file.cs")]
    [InlineData("src/../../x.cs")]
    [InlineData("/etc/passwd")]
    [InlineData("C:\\Windows\\win.ini")]
    [InlineData("~/secret")]
    public async Task Content_RejectsPathsOutsideTheRepository(string path)
    {
        var (service, minio) = await CreateAsync();

        var result = await service.ContentAsync(100, new SourceContentRequest(10, 1, path));

        Assert.Equal(SourceLookupStatus.Invalid, result.Status);
        Assert.Empty(minio.Requested);
    }

    [Fact]
    public async Task Content_OnlyServesFilesRegisteredForTheProject()
    {
        var (service, minio) = await CreateAsync();

        var result = await service.ContentAsync(100, new SourceContentRequest(10, 1, "src/Secret.cs"));

        Assert.Equal(SourceLookupStatus.FileNotFound, result.Status);
        Assert.Empty(minio.Requested);
    }

    [Fact]
    public async Task Content_ReturnsBoundedLineRange()
    {
        var (service, _) = await CreateAsync();

        var result = await service.ContentAsync(100, new SourceContentRequest(10, 1, "src\\Services\\PaymentService.cs", 3, 99, maxLines: 2));

        Assert.Equal(SourceLookupStatus.Found, result.Status);
        Assert.Equal(5, result.Data!.TotalLines);
        Assert.Equal(3, result.Data.StartLine);
        Assert.Equal(4, result.Data.EndLine);
        Assert.Equal(new[] { "  void Process() { Charge(); }", "  void Charge() { }" }, result.Data.Lines);
        Assert.True(result.Data.Truncated);
    }

    [Fact]
    public async Task Content_ReportsMissingStorageObject()
    {
        var (service, minio) = await CreateAsync();
        minio.Objects.Remove(ServicePath);

        var result = await service.ContentAsync(100, new SourceContentRequest(10, 1, "src/Services/PaymentService.cs"));

        Assert.Equal(SourceLookupStatus.ObjectMissing, result.Status);
    }

    [Fact]
    public async Task Search_FindsLiteralAndRegexMatchesInCodeFiles()
    {
        var (service, _) = await CreateAsync();

        var literal = await service.SearchAsync(100, new SourceSearchRequest(10, 1, "Process()"));
        var regex = await service.SearchAsync(100, new SourceSearchRequest(10, 1, @"void \w+\(\)", isRegex: true, pathGlob: "src/Services/**"));

        Assert.Equal(new[] { ("src/Services/PaymentService.cs", 3), ("src/Api/Api.cs", 1) },
            literal.Data!.Matches.Select(m => (m.Path, m.Line)).OrderByDescending(m => m.Item1));
        Assert.All(regex.Data!.Matches, m => Assert.Equal("src/Services/PaymentService.cs", m.Path));
        Assert.Equal(2, regex.Data.Matches.Count);
    }

    [Fact]
    public async Task Search_RejectsInvalidRegexAndLimitsResults()
    {
        var (service, _) = await CreateAsync();

        Assert.Equal(SourceLookupStatus.Invalid, (await service.SearchAsync(100, new SourceSearchRequest(10, 1, "([a-z", isRegex: true))).Status);

        var limited = await service.SearchAsync(100, new SourceSearchRequest(10, 1, "void", maxResults: 1));
        Assert.Single(limited.Data!.Matches);
        Assert.True(limited.Data.Truncated);
    }

    [Theory]
    [InlineData("src/**/*.cs", "src/Services/PaymentService.cs", true)]
    [InlineData("src/*.cs", "src/Services/PaymentService.cs", false)]
    [InlineData("**/Api.cs", "src/Api/Api.cs", true)]
    public void GlobToRegex_MatchesRepositoryPaths(string glob, string path, bool expected)
    {
        Assert.Equal(expected, SourceAccessService.GlobToRegex(glob)!.IsMatch(path));
    }
}

public class InternalSourceControllerTests
{
    private static IConfiguration Config() =>
        new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string, string?> { ["Internal:ApiKey"] = "k" }).Build();

    private static InternalSourceController Controller(SourceAccessService service, string? key)
    {
        var http = new DefaultHttpContext();
        if (key != null) http.Request.Headers[InternalKey.Header] = key;
        return new InternalSourceController(service, Config()) { ControllerContext = new ControllerContext { HttpContext = http } };
    }

    [Fact]
    public async Task RequiresInternalKey()
    {
        var service = new SourceAccessService(MetricsServiceTests.CreateDb(), new FakeMinioService());

        Assert.IsType<UnauthorizedResult>(await Controller(service, null).Files(100, new SourceFilesRequest(10, 1)));
        Assert.IsType<UnauthorizedResult>(await Controller(service, "wrong").Files(100, new SourceFilesRequest(10, 1)));
    }

    [Fact]
    public async Task MapsLookupStatusToHttp()
    {
        var db = await MetricsServiceTests.SeedProjectsAsync(MetricsServiceTests.CreateDb());
        var service = new SourceAccessService(db, new FakeMinioService());

        Assert.Equal(StatusCodes.Status403Forbidden, Assert.IsType<StatusCodeResult>(await Controller(service, "k").Files(100, new SourceFilesRequest(20, 1))).StatusCode);
        Assert.IsType<BadRequestObjectResult>(await Controller(service, "k").Content(100, new SourceContentRequest(10, 1, "../x.cs")));
        Assert.IsType<NotFoundObjectResult>(await Controller(service, "k").Content(100, new SourceContentRequest(10, 1, "src/none.cs")));
        Assert.IsType<OkObjectResult>(await Controller(service, "k").Files(100, new SourceFilesRequest(10, 1)));
    }
}

public class ChatAgentContractTests
{
    [Fact]
    public async Task SendMessageAsync_PassesModeAndKeepsAgentFields()
    {
        var json = """
        {
            "data": {
                "answer": "checkout calls it [GRAPH_1].",
                "status": "verified",
                "citations": [ { "alias": "GRAPH_1", "type": "graph", "evidenceIds": ["rel:1"] } ],
                "execution": { "strategy": "evidence_aware_agentic_rag", "toolCalls": 2, "stopReason": "evidence_sufficient" },
                "rawEvidence": [ { "evidence_id": "rel:1" } ],
                "patternAnalysis": { "preferred_alternative": "minimal_change", "no_pattern_needed": true, "recommended_patterns": [] },
                "evidence": [
                    {
                        "id": "GRAPH_1", "type": "graph", "evidenceIds": ["rel:1"], "producedBy": ["get_callers"],
                        "nodes": [ { "id": "a", "label": "checkout", "type": "Function" }, { "id": "b", "label": "pay", "type": "Method" } ],
                        "edges": [ { "source": "a", "target": "b", "type": "CALLS", "certainty": "inferred" } ]
                    }
                ]
            }
        }
        """;
        var handler = new CapturingHandler(json);
        var config = new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string, string?> { ["AI:PythonUrl"] = "http://py" }).Build();
        var service = new ChatService(MetricsServiceTests.CreateDb(), new HttpClient(handler), config);

        var result = await service.SendMessageAsync(1, new ChatRequest("?", 1, 1, "evidence_aware_agentic_rag"));

        Assert.Contains("\"mode\":\"evidence_aware_agentic_rag\"", handler.Body);
        var answer = Assert.IsType<ChatAnswer>(result.Data);
        Assert.Equal("verified", answer.Status);
        Assert.Equal(2, answer.Execution!.Value.GetProperty("toolCalls").GetInt32());
        Assert.Equal("GRAPH_1", answer.Citations!.Value[0].GetProperty("alias").GetString());
        Assert.Equal("minimal_change", answer.PatternAnalysis!.Value.GetProperty("preferred_alternative").GetString());
        var graph = Assert.IsType<GraphEvidence>(Assert.Single(answer.Evidence));
        Assert.Equal("inferred", graph.Edges[0].Certainty);
        Assert.Equal(new[] { "rel:1" }, graph.EvidenceIds);

        var serialized = JsonSerializer.Serialize(answer, EvidenceJson.Options);
        Assert.Contains("\"execution\":{", serialized);
        Assert.Contains("\"patternAnalysis\":{", serialized);
        Assert.Contains("\"certainty\":\"inferred\"", serialized);
    }

    [Fact]
    public async Task SendMessageAsync_LegacyResponsesStayValid()
    {
        var config = new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string, string?> { ["AI:PythonUrl"] = "http://py" }).Build();
        var service = new ChatService(MetricsServiceTests.CreateDb(), new HttpClient(new CapturingHandler("""{ "data": { "answer": "ok", "evidence": [] } }""")), config);

        var answer = Assert.IsType<ChatAnswer>((await service.SendMessageAsync(1, new ChatRequest("?", 1, 1))).Data);

        Assert.Equal("ok", answer.Answer);
        Assert.Null(answer.Status);
        Assert.Null(answer.Execution);
        Assert.Null(answer.PatternAnalysis);
    }

    private class CapturingHandler : HttpMessageHandler
    {
        private readonly string response;
        public string Body { get; private set; } = "";

        public CapturingHandler(string responseBody) => response = responseBody;

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Body = request.Content == null ? "" : await request.Content.ReadAsStringAsync(cancellationToken);
            return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(response, Encoding.UTF8, "application/json") };
        }
    }
}
