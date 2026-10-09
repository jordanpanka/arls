using System.Net;
using System.Security.Claims;
using System.Text;
using System.Text.Json;
using ef;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Xunit;

public class MetricsAggregatorTests
{
    private static readonly MetricsThresholds T = new();

    private static AiFunctionMetrics Fn(string name, int ccn, int nloc = 10, int parameters = 1, int start = 1) =>
        new(name, name + "()", null, start, start + nloc, nloc, ccn, nloc * 5, parameters, nloc + 1);

    [Theory]
    [InlineData(1, ComplexityCategory.Low)]
    [InlineData(5, ComplexityCategory.Low)]
    [InlineData(6, ComplexityCategory.Moderate)]
    [InlineData(10, ComplexityCategory.Moderate)]
    [InlineData(11, ComplexityCategory.High)]
    [InlineData(20, ComplexityCategory.High)]
    [InlineData(21, ComplexityCategory.VeryHigh)]
    public void Categorize_UsesConfiguredBands(int ccn, string expected)
    {
        Assert.Equal(expected, MetricsAggregator.Categorize(ccn, T));
    }

    [Fact]
    public void BuildFile_AggregatesFunctionMetrics()
    {
        var file = MetricsAggregator.BuildFile(new AiFileMetrics("src\\A.cs", "csharp", 120, 900, 1, new()
        {
            Fn("Small", 2, nloc: 10),
            Fn("Long", 12, nloc: 60, parameters: 7),
            Fn("Tangled", 27, nloc: 30),
        }), T);

        Assert.Equal("src/A.cs", file.Path);
        Assert.Equal(3, file.FunctionCount);
        Assert.Equal((2 + 12 + 27) / 3.0, file.AverageComplexity!.Value, 6);
        Assert.Equal(27, file.MaxComplexity);
        Assert.Equal(2, file.HighComplexityFunctionCount);
        Assert.Equal(1, file.LongFunctionCount);
        Assert.Equal(1, file.ManyParameterFunctionCount);
        Assert.Equal(60, file.MaxFunctionNloc);
    }

    [Fact]
    public void BuildFile_WithoutFunctions_LeavesAveragesUnavailable()
    {
        var file = MetricsAggregator.BuildFile(new AiFileMetrics("src/Consts.cs", "csharp", 4, 20, 1, new()), T);

        Assert.Null(file.AverageComplexity);
        Assert.Null(file.MaxComplexity);
        Assert.Equal(0, file.FunctionCount);
    }

    [Fact]
    public void ApplyRepository_AveragesOverAllFunctions_NotOverFileAverages()
    {
        var a = MetricsAggregator.BuildFile(new AiFileMetrics("a.py", "python", 10, 1, null, new() { Fn("x", 1), Fn("y", 1), Fn("z", 1) }), T);
        var b = MetricsAggregator.BuildFile(new AiFileMetrics("b.py", "python", 20, 1, 2, new() { Fn("w", 9) }), T);
        var analysis = new DbMetricsAnalysis();

        MetricsAggregator.ApplyRepository(analysis, new[] { a, b }, null, T);

        Assert.Equal(2, analysis.FilesAnalyzed);
        Assert.Equal(30, analysis.TotalNloc);
        Assert.Equal(4, analysis.TotalFunctions);
        Assert.Equal(2, analysis.TotalClasses);
        Assert.Equal(3.0, analysis.AverageComplexity);
        Assert.Equal(9, analysis.MaxComplexity);
        Assert.Null(analysis.DependencyCount);
    }

    [Fact]
    public void ApplyGraph_MatchesFilesByPathAndFunctionsByShortName()
    {
        var file = MetricsAggregator.BuildFile(new AiFileMetrics("src/A.cs", "csharp", 10, 1, 1, new() { Fn("Run", 3) }), T);
        var other = MetricsAggregator.BuildFile(new AiFileMetrics("src/NotInGraph.cs", "csharp", 10, 1, 1, new()), T);
        var graph = new AiGraphResult("neo4j", new() { new("src/A.cs", 2, 3, 4) },
            new() { new("src/A.cs", "Service.Run", 1, 5, 6, 0) }, 3, 0, new(), 1, 0, 0, 1);

        MetricsAggregator.ApplyGraph(new[] { file, other }, graph);
        var analysis = new DbMetricsAnalysis();
        MetricsAggregator.ApplyRepository(analysis, new[] { file, other }, graph, T);

        Assert.Equal((2, 3, 4), (file.FanIn, file.FanOut, file.ImportCount));
        Assert.Equal((5, 6), (file.Functions[0].FanIn, file.Functions[0].FanOut));
        Assert.Null(other.FanIn);
        Assert.Equal(2.0, analysis.AverageFanIn);
        Assert.Equal(3, analysis.DependencyCount);
    }

    [Fact]
    public void Distribution_CountsFunctionsPerBand()
    {
        var buckets = MetricsAggregator.Distribution(new[] { 1, 3, 7, 15, 30, 31 }, T);

        Assert.Equal(new[] { "1–5", "6–10", "11–20", "21+" }, buckets.Select(b => b.Label));
        Assert.Equal(new[] { 2, 1, 1, 2 }, buckets.Select(b => b.Count));
    }

    [Fact]
    public void CodeExtensions_AllHaveALanguage()
    {
        foreach (var extension in SourceLanguage.CodeExtensions)
            Assert.NotEqual("plaintext", SourceLanguage.FromPath("file" + extension));
    }
}

public class MetricsServiceTests
{
    internal static CodeDbContext CreateDb() =>
        new(new DbContextOptionsBuilder<CodeDbContext>().UseInMemoryDatabase(Guid.NewGuid().ToString()).Options);

    internal static IOptions<MetricsOptions> Options() => Microsoft.Extensions.Options.Options.Create(new MetricsOptions());

    internal static async Task<CodeDbContext> SeedProjectsAsync(CodeDbContext db)
    {
        db.Investigations.AddRange(
            new DbInvestigation { ID = 1, UserID = 10, Name = "Mine", Description = "" },
            new DbInvestigation { ID = 2, UserID = 20, Name = "Theirs", Description = "" });
        db.Projects.AddRange(
            new DbProject { ID = 100, InvestigationID = 1, Name = "P", Description = "" },
            new DbProject { ID = 200, InvestigationID = 2, Name = "Other", Description = "" });
        await db.SaveChangesAsync();
        return db;
    }

    private static DbFunctionMetric Fn(string name, int ccn, int start, int nloc = 10, int? fanIn = null) =>
        new() { Name = name, LongName = name, StartLine = start, EndLine = start + nloc, Nloc = nloc, CyclomaticComplexity = ccn, FanIn = fanIn, FanOut = fanIn };

    private static async Task<CodeDbContext> SeedAnalysisAsync()
    {
        var db = await SeedProjectsAsync(CreateDb());
        db.MetricsAnalyses.Add(new DbMetricsAnalysis
        {
            ID = 1, ProjectID = 100, Status = MetricsAnalysisStatus.Failed, CompletedAt = DateTime.UtcNow.AddDays(-1),
        });
        db.MetricsAnalyses.Add(new DbMetricsAnalysis
        {
            ID = 2, ProjectID = 100, Status = MetricsAnalysisStatus.Completed, CompletedAt = DateTime.UtcNow,
            FilesAnalyzed = 2, TotalNloc = 300, TotalFunctions = 4, AverageComplexity = 10.5, MaxComplexity = 27,
            HighComplexityFunctionCount = 2, DependencyCount = 1, AverageFanIn = 0.5, MaxFanIn = 1,
            ThresholdsJson = JsonSerializer.Serialize(new MetricsThresholds()),
            Files = new()
            {
                new DbFileMetric
                {
                    Path = "src/UserService.cs", FileID = 7, Language = "csharp", Nloc = 200, FunctionCount = 3,
                    AverageComplexity = 13, MaxComplexity = 27, FanIn = 1, FanOut = 0,
                    Functions = new() { Fn("CreateUser", 27, 120, fanIn: 3), Fn("CreateUser", 4, 300), Fn("Ping", 1, 10) },
                },
                new DbFileMetric
                {
                    Path = "src/Util.cs", Language = "csharp", Nloc = 100, FunctionCount = 1,
                    AverageComplexity = 7, MaxComplexity = 7, FanIn = 0, FanOut = 1,
                    Functions = new() { Fn("Format", 7, 5, fanIn: 9) },
                },
            },
        });
        await db.SaveChangesAsync();
        return db;
    }

    [Fact]
    public async Task GetRepositoryMetrics_ReturnsLatestUsableAnalysis()
    {
        var service = new MetricsService(await SeedAnalysisAsync(), Options());

        var result = await service.GetRepositoryMetricsAsync(10, 100);

        Assert.Equal(MetricsLookupStatus.Found, result.Status);
        Assert.Equal(2, result.Data!.Analysis.AnalysisId);
        Assert.Equal(300, result.Data.Summary.TotalNloc);
        Assert.Equal(ComplexityCategory.VeryHigh, result.Data.Summary.MaxComplexityCategory);
        Assert.Equal(4, result.Data.ComplexityDistribution.Sum(b => b.Count));
        Assert.Equal(new[] { 2, 1, 0, 1 }, result.Data.ComplexityDistribution.Select(b => b.Count));
    }

    [Fact]
    public async Task GetRepositoryMetrics_WithoutAnalysis_ReportsNoAnalysis()
    {
        var service = new MetricsService(await SeedProjectsAsync(CreateDb()), Options());

        var result = await service.GetRepositoryMetricsAsync(10, 100);

        Assert.Equal(MetricsLookupStatus.NoAnalysis, result.Status);
    }

    [Fact]
    public async Task GetRepositoryMetrics_ForOtherUsersProject_IsForbidden()
    {
        var service = new MetricsService(await SeedAnalysisAsync(), Options());

        Assert.Equal(MetricsLookupStatus.Forbidden, (await service.GetRepositoryMetricsAsync(20, 100)).Status);
        Assert.Equal(MetricsLookupStatus.ProjectNotFound, (await service.GetRepositoryMetricsAsync(10, 999)).Status);
    }

    [Fact]
    public async Task Hotspots_AreRankedByFocus()
    {
        var service = new MetricsService(await SeedAnalysisAsync(), Options());

        var complexity = await service.GetComplexityHotspotsAsync(10, 100, 10);
        var dependency = await service.GetDependencyHotspotsAsync(10, 100, 10);

        Assert.Equal(new[] { "src/UserService.cs", "src/Util.cs" }, complexity.Data!.Files.Select(f => f.Path));
        Assert.Equal(new[] { 27, 7, 4, 1 }, complexity.Data.Functions.Select(f => f.CyclomaticComplexity));
        Assert.Equal("Format", dependency.Data!.Functions.First().Name);
    }

    [Fact]
    public async Task GetFileDetail_ReturnsFunctionsByComplexity()
    {
        var service = new MetricsService(await SeedAnalysisAsync(), Options());

        var detail = await service.GetFileDetailAsync(10, 100, "/src\\UserService.cs");

        Assert.Equal(7, detail.Data!.File.FileId);
        Assert.Equal(new[] { 27, 4, 1 }, detail.Data.Functions.Select(f => f.CyclomaticComplexity));
        Assert.Equal(MetricsLookupStatus.NotFound, (await service.GetFileDetailAsync(10, 100, "src/Missing.cs")).Status);
    }

    [Fact]
    public async Task RagEvidence_ReturnsOnlyRequestedEntities_AndPicksNearestOverload()
    {
        var service = new MetricsService(await SeedAnalysisAsync(), Options());

        var result = await service.GetRagEvidenceAsync(100, new RagMetricsRequest(
            10, 1, new() { "src/UserService.cs" }, new() { new("src/UserService.cs", "UserService.CreateUser", 298) }, false, null, null));

        Assert.Equal(MetricsLookupStatus.Found, result.Status);
        var data = result.Data!;
        Assert.Null(data.Repository);
        Assert.Empty(data.HotspotFiles);
        Assert.Equal("src/UserService.cs", Assert.Single(data.Files).Path);
        var function = Assert.Single(data.Functions);
        Assert.Equal((300, 4), (function.StartLine, function.CyclomaticComplexity));
    }

    [Fact]
    public async Task RagEvidence_RepositoryScope_AddsSummaryAndHotspots()
    {
        var service = new MetricsService(await SeedAnalysisAsync(), Options());

        var result = await service.GetRagEvidenceAsync(100, new RagMetricsRequest(10, 1, null, null, true, "complexity", 1));

        Assert.Equal(300, result.Data!.Repository!.TotalNloc);
        Assert.Equal("src/UserService.cs", Assert.Single(result.Data.HotspotFiles).Path);
    }

    [Fact]
    public async Task RagEvidence_RejectsMismatchedUserOrInvestigation()
    {
        var service = new MetricsService(await SeedAnalysisAsync(), Options());

        Assert.Equal(MetricsLookupStatus.Forbidden, (await service.GetRagEvidenceAsync(100, new RagMetricsRequest(20, 1, null, null, true, null, null))).Status);
        Assert.Equal(MetricsLookupStatus.Forbidden, (await service.GetRagEvidenceAsync(100, new RagMetricsRequest(10, 2, null, null, true, null, null))).Status);
    }
}

public class MetricsAnalysisServiceTests
{
    private const string StaticResponse = """
    {"is_success": true, "message": null, "data": {
      "analyzer": "lizard", "durationMs": 12.5,
      "files": [{"path": "src/A.cs", "language": "csharp", "nloc": 40, "tokenCount": 300, "classCount": 1,
        "functions": [
          {"name": "Run", "longName": "A::Run()", "className": "A", "startLine": 3, "endLine": 30, "nloc": 25,
           "cyclomaticComplexity": 12, "tokenCount": 200, "parameterCount": 2, "length": 28},
          {"name": "Stop", "longName": "A::Stop()", "className": "A", "startLine": 32, "endLine": 35, "nloc": 4,
           "cyclomaticComplexity": 1, "tokenCount": 20, "parameterCount": 0, "length": 4}]}],
      "skipped": [{"path": "src/B.cs", "reason": "analyzer_error"}]}}
    """;

    private const string GraphResponse = """
    {"is_success": true, "message": null, "data": {
      "analyzer": "neo4j-knowledge-graph", "durationMs": 3,
      "files": [{"path": "src/A.cs", "fanIn": 2, "fanOut": 1, "importCount": 4}],
      "functions": [{"path": "src/A.cs", "name": "Run", "startLine": 3, "fanIn": 2, "fanOut": 1, "unresolvedCalls": 0}],
      "dependencyCount": 3, "cycleCount": 1, "cycles": [["src/A.cs", "src/C.cs"]], "maxDependencyDepth": 2,
      "ambiguousCalls": 0, "unresolvedCalls": 0}}
    """;

    private static async Task<CodeDbContext> SeedAsync()
    {
        var db = await MetricsServiceTests.SeedProjectsAsync(MetricsServiceTests.CreateDb());
        db.Files.AddRange(
            new DbFile { ID = 1, ProjectID = 100, Name = "A.cs", RelativePath = "src/A.cs", StoragePath = "", Extension = ".cs", Size = 10 },
            new DbFile { ID = 2, ProjectID = 100, Name = "B.cs", RelativePath = "src/B.cs", StoragePath = "", Extension = ".cs", Size = 10 },
            new DbFile { ID = 3, ProjectID = 100, Name = "Gone.cs", RelativePath = "src/Gone.cs", StoragePath = "", Extension = ".cs", Size = 10 },
            new DbFile { ID = 4, ProjectID = 100, Name = "README.md", RelativePath = "README.md", StoragePath = "", Extension = ".md", Size = 10 });
        db.Repositories.Add(new DbRepository { ID = 5, ProjectID = 100, Owner = "o", Name = "r", Reference = "main", CommitSha = "abc123", Status = RepositoryStatus.Ready, IndexedAt = DateTime.UtcNow });
        await db.SaveChangesAsync();
        return db;
    }

    private static FakeMinioService Minio()
    {
        var minio = new FakeMinioService();
        minio.Objects["users/10/investigations/1/projects/100/original/src/A.cs"] = Encoding.UTF8.GetBytes("class A {}");
        minio.Objects["users/10/investigations/1/projects/100/original/src/B.cs"] = Encoding.UTF8.GetBytes("class B {}");
        return minio;
    }

    private static MetricsAnalysisService Create(CodeDbContext db, RoutingHttpHandler handler, FakeMinioService minio, MetricsAnalysisQueue? queue = null) =>
        new(db, new HttpClient(handler),
            new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string, string?> { ["AI:PythonUrl"] = "http://test-python" }).Build(),
            minio, queue ?? new MetricsAnalysisQueue(), MetricsServiceTests.Options(), NullLogger<MetricsAnalysisService>.Instance);

    [Fact]
    public async Task RunAsync_PersistsStaticAndGraphMetrics()
    {
        var db = await SeedAsync();
        var handler = new RoutingHttpHandler { ["/api/metrics/static"] = (HttpStatusCode.OK, StaticResponse), ["/api/metrics/graph"] = (HttpStatusCode.OK, GraphResponse) };
        var minio = Minio();
        var service = Create(db, handler, minio);

        var queued = await service.QueueAsync(10, 100, force: false);
        await service.RunAsync(queued.Data!.AnalysisId);

        var analysis = await db.MetricsAnalyses.Include(a => a.Files).ThenInclude(f => f.Functions).SingleAsync();
        Assert.Equal(MetricsAnalysisStatus.Completed, analysis.Status);
        Assert.Equal((MetricsPhaseStatus.Completed, MetricsPhaseStatus.Completed), (analysis.StaticStatus, analysis.GraphStatus));
        Assert.Equal(("main", "abc123", 5), (analysis.Branch, analysis.CommitSha, analysis.RepositoryID));
        Assert.Equal(1, analysis.FilesAnalyzed);
        Assert.Equal(2, analysis.FilesSkipped);
        Assert.Contains("missing_in_storage", analysis.SkippedFilesJson);
        Assert.Equal(6.5, analysis.AverageComplexity);
        Assert.Equal(12, analysis.MaxComplexity);
        Assert.Equal(1, analysis.HighComplexityFunctionCount);
        Assert.Equal((3, 1, 2), (analysis.DependencyCount, analysis.CycleCount, analysis.MaxDependencyDepth));
        Assert.NotNull(analysis.TotalDurationMs);

        var file = Assert.Single(analysis.Files);
        Assert.Equal((1, 2, 1), (file.FileID, file.FanIn, file.FanOut));
        Assert.Equal(2, file.Functions.Single(f => f.Name == "Run").FanIn);
        Assert.DoesNotContain(minio.Requested, r => r.EndsWith("README.md"));
        Assert.Equal(2, handler.Requests.Count);
    }

    [Fact]
    public async Task RunAsync_GraphFailure_KeepsStaticMetricsAsPartial()
    {
        var db = await SeedAsync();
        var handler = new RoutingHttpHandler
        {
            ["/api/metrics/static"] = (HttpStatusCode.OK, StaticResponse),
            ["/api/metrics/graph"] = (HttpStatusCode.OK, """{"is_success": false, "message": "Neo4j unavailable", "data": null}"""),
        };
        var service = Create(db, handler, Minio());

        var queued = await service.QueueAsync(10, 100, force: false);
        await service.RunAsync(queued.Data!.AnalysisId);

        var analysis = await db.MetricsAnalyses.Include(a => a.Files).SingleAsync();
        Assert.Equal(MetricsAnalysisStatus.Partial, analysis.Status);
        Assert.Equal(MetricsPhaseStatus.Failed, analysis.GraphStatus);
        Assert.Contains("Neo4j unavailable", analysis.ErrorMessage);
        Assert.Null(analysis.DependencyCount);
        Assert.Null(Assert.Single(analysis.Files).FanIn);
        Assert.Equal(12, analysis.MaxComplexity);
    }

    [Fact]
    public async Task RunAsync_StaticFailure_MarksAnalysisFailed()
    {
        var db = await SeedAsync();
        var handler = new RoutingHttpHandler { ["/api/metrics/static"] = (HttpStatusCode.InternalServerError, "boom") };
        var service = Create(db, handler, Minio());

        var queued = await service.QueueAsync(10, 100, force: false);
        await service.RunAsync(queued.Data!.AnalysisId);

        var analysis = await db.MetricsAnalyses.SingleAsync();
        Assert.Equal(MetricsAnalysisStatus.Failed, analysis.Status);
        Assert.Equal(MetricsPhaseStatus.Failed, analysis.StaticStatus);
        Assert.Empty(db.FileMetrics);
    }

    [Fact]
    public async Task QueueAsync_ReusesUnchangedAnalysis_UnlessForced()
    {
        var db = await SeedAsync();
        var handler = new RoutingHttpHandler { ["/api/metrics/static"] = (HttpStatusCode.OK, StaticResponse), ["/api/metrics/graph"] = (HttpStatusCode.OK, GraphResponse) };
        var service = Create(db, handler, Minio());

        var first = await service.QueueAsync(10, 100, force: false);
        Assert.True((await service.QueueAsync(10, 100, force: false)).Data!.Reused);
        await service.RunAsync(first.Data!.AnalysisId);

        var again = await service.QueueAsync(10, 100, force: false);
        var forced = await service.QueueAsync(10, 100, force: true);

        Assert.True(again.Data!.Reused);
        Assert.Equal(first.Data.AnalysisId, again.Data.AnalysisId);
        Assert.False(forced.Data!.Reused);
        Assert.Equal(MetricsLookupStatus.Forbidden, (await service.QueueAsync(20, 100, false)).Status);
    }
}

public class MetricsControllerTests
{
    private static ControllerContext Context(int userId, string? internalKey = null)
    {
        var http = new DefaultHttpContext
        {
            User = new ClaimsPrincipal(new ClaimsIdentity(new[] { new Claim("uid", userId.ToString()) }, "test")),
        };
        if (internalKey != null) http.Request.Headers[InternalMetricsController.KeyHeader] = internalKey;
        return new ControllerContext { HttpContext = http };
    }

    [Fact]
    public async Task Repository_WithoutAnalysis_Returns404WithNoAnalysisCode()
    {
        var db = await MetricsServiceTests.SeedProjectsAsync(MetricsServiceTests.CreateDb());
        var controller = new MetricsController(new MetricsService(db, MetricsServiceTests.Options()), null!) { ControllerContext = Context(10) };

        var result = Assert.IsType<NotFoundObjectResult>(await controller.Repository(100));

        Assert.Contains("no_analysis", JsonSerializer.Serialize(result.Value));
    }

    [Fact]
    public async Task Repository_ForOtherUser_Returns403()
    {
        var db = await MetricsServiceTests.SeedProjectsAsync(MetricsServiceTests.CreateDb());
        var controller = new MetricsController(new MetricsService(db, MetricsServiceTests.Options()), null!) { ControllerContext = Context(20) };

        var result = Assert.IsType<ObjectResult>(await controller.Repository(100));

        Assert.Equal(StatusCodes.Status403Forbidden, result.StatusCode);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("wrong-key")]
    public async Task InternalEvidence_RequiresTheSharedKey(string? key)
    {
        var db = await MetricsServiceTests.SeedProjectsAsync(MetricsServiceTests.CreateDb());
        var config = new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string, string?> { ["Internal:ApiKey"] = "secret" }).Build();
        var controller = new InternalMetricsController(new MetricsService(db, MetricsServiceTests.Options()), config) { ControllerContext = Context(10, key) };

        Assert.IsType<UnauthorizedResult>(await controller.Evidence(100, new RagMetricsRequest(10, 1, null, null, true, null, null)));
    }

    [Fact]
    public async Task InternalEvidence_WithKeyButNoAnalysis_Returns404()
    {
        var db = await MetricsServiceTests.SeedProjectsAsync(MetricsServiceTests.CreateDb());
        var config = new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string, string?> { ["Internal:ApiKey"] = "secret" }).Build();
        var controller = new InternalMetricsController(new MetricsService(db, MetricsServiceTests.Options()), config) { ControllerContext = Context(10, "secret") };

        Assert.IsType<NotFoundObjectResult>(await controller.Evidence(100, new RagMetricsRequest(10, 1, null, null, true, null, null)));
    }

    [Fact]
    public void MetricEvidence_RoundTripsThroughEvidenceJson()
    {
        var json = """
        [{"type": "metric", "id": "METRIC_1", "scope": "function", "title": "A.Run()", "filePath": "src/A.cs",
          "startLine": 3, "endLine": 30, "analysisId": 2,
          "items": [{"key": "cyclomaticComplexity", "label": "Cyclomatic complexity", "value": 27, "category": "VeryHigh"},
                    {"key": "fanIn", "label": "Fan-in", "value": null}]}]
        """;

        var parsed = EvidenceJson.ParseList(JsonDocument.Parse(json).RootElement);

        var metric = Assert.IsType<MetricEvidence>(Assert.Single(parsed));
        Assert.Equal(27.0, metric.Items[0].Value);
        Assert.Null(metric.Items[1].Value);
        Assert.Contains("\"type\":\"metric\"", JsonSerializer.Serialize<Evidence>(metric, EvidenceJson.Options));
    }
}

public class RoutingHttpHandler : HttpMessageHandler
{
    private readonly Dictionary<string, (HttpStatusCode Status, string Body)> routes = new();

    public List<string> Requests { get; } = new();

    public (HttpStatusCode Status, string Body) this[string path]
    {
        set => routes[path] = value;
    }

    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        var path = request.RequestUri!.AbsolutePath;
        Requests.Add(path);
        var (status, body) = routes.TryGetValue(path, out var route) ? route : (HttpStatusCode.NotFound, "{}");
        return Task.FromResult(new HttpResponseMessage(status) { Content = new StringContent(body, Encoding.UTF8, "application/json") });
    }
}
