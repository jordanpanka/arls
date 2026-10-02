using System.Security.Claims;
using System.Text;
using ef;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Xunit;

public class FileServiceTests
{
    private CodeDbContext CreateDb()
    {
        var options = new DbContextOptionsBuilder<CodeDbContext>()
            .UseInMemoryDatabase(Guid.NewGuid().ToString())
            .Options;

        return new CodeDbContext(options);
    }

    private static async Task<CodeDbContext> SeedAsync(CodeDbContext db)
    {
        db.Investigations.AddRange(
            new DbInvestigation { ID = 1, UserID = 10, Name = "Mine", Description = "" },
            new DbInvestigation { ID = 2, UserID = 20, Name = "Theirs", Description = "" });
        db.Projects.AddRange(
            new DbProject { ID = 100, InvestigationID = 1, Name = "P1", Description = "" },
            new DbProject { ID = 101, InvestigationID = 1, Name = "P2", Description = "" },
            new DbProject { ID = 200, InvestigationID = 2, Name = "Other", Description = "" });
        db.Files.AddRange(
            new DbFile { ID = 1, ProjectID = 100, Name = "UserService.cs", RelativePath = "src/Services/UserService.cs", StoragePath = "", Extension = ".cs" },
            new DbFile { ID = 2, ProjectID = 101, Name = "Other.cs", RelativePath = "src/Other.cs", StoragePath = "", Extension = ".cs" },
            new DbFile { ID = 3, ProjectID = 200, Name = "Secret.cs", RelativePath = "src/Secret.cs", StoragePath = "", Extension = ".cs" });
        await db.SaveChangesAsync();
        return db;
    }

    private static FilesController CreateController(CodeDbContext db, FakeMinioService minio, int userId)
    {
        var fileService = new FileService(db, new HttpClient(), new ConfigurationBuilder().Build());
        return new FilesController(fileService, minio)
        {
            ControllerContext = new ControllerContext
            {
                HttpContext = new DefaultHttpContext
                {
                    User = new ClaimsPrincipal(new ClaimsIdentity(new[] { new Claim("uid", userId.ToString()) }, "test"))
                }
            }
        };
    }

    [Fact]
    public async Task FindProjectFileAsync_ReturnsFile_ForOwner()
    {
        var db = await SeedAsync(CreateDb());
        var service = new FileService(db, new HttpClient(), new ConfigurationBuilder().Build());

        var lookup = await service.FindProjectFileAsync(10, 100, 1);

        Assert.Equal(FileLookupStatus.Found, lookup.Status);
        Assert.Equal("src/Services/UserService.cs", lookup.File!.RelativePath);
        Assert.Equal(1, lookup.InvestigationId);
    }

    [Fact]
    public async Task GetFileContent_ReturnsContentFromStorage()
    {
        var db = await SeedAsync(CreateDb());
        var minio = new FakeMinioService();
        minio.Objects["users/10/investigations/1/projects/100/original/src/Services/UserService.cs"] =
            Encoding.UTF8.GetBytes("class UserService {}\n");

        var result = await CreateController(db, minio, 10).GetFileContent(100, 1);

        var ok = Assert.IsType<OkObjectResult>(result);
        var file = Assert.IsType<ProjectFileContent>(ok.Value);
        Assert.Equal("1", file.FileId);
        Assert.Equal("UserService.cs", file.FileName);
        Assert.Equal("src/Services/UserService.cs", file.FilePath);
        Assert.Equal("csharp", file.Language);
        Assert.Equal("class UserService {}\n", file.Content);
    }

    [Fact]
    public async Task GetFileContent_RejectsProjectOfAnotherUser()
    {
        var db = await SeedAsync(CreateDb());
        var minio = new FakeMinioService();
        minio.Objects["users/20/investigations/2/projects/200/original/src/Secret.cs"] = Encoding.UTF8.GetBytes("secret");

        var result = await CreateController(db, minio, 10).GetFileContent(200, 3);

        var status = Assert.IsType<ObjectResult>(result);
        Assert.Equal(StatusCodes.Status403Forbidden, status.StatusCode);
        Assert.Empty(minio.Requested);
    }

    [Fact]
    public async Task GetFileContent_RejectsFileFromAnotherProject()
    {
        var db = await SeedAsync(CreateDb());
        var minio = new FakeMinioService();

        var result = await CreateController(db, minio, 10).GetFileContent(100, 2);

        Assert.IsType<NotFoundObjectResult>(result);
        Assert.Empty(minio.Requested);
    }

    [Fact]
    public async Task GetFileContent_ReturnsNotFound_WhenStorageObjectMissing()
    {
        var db = await SeedAsync(CreateDb());

        var result = await CreateController(db, new FakeMinioService(), 10).GetFileContent(100, 1);

        Assert.IsType<NotFoundObjectResult>(result);
    }

    [Fact]
    public async Task GetFileContent_RefusesBinaryFiles()
    {
        var db = await SeedAsync(CreateDb());
        var minio = new FakeMinioService();
        minio.Objects["users/10/investigations/1/projects/100/original/src/Services/UserService.cs"] = new byte[] { 1, 0, 2 };

        var result = await CreateController(db, minio, 10).GetFileContent(100, 1);

        Assert.Equal(StatusCodes.Status415UnsupportedMediaType, Assert.IsType<ObjectResult>(result).StatusCode);
    }
}

public class FakeMinioService : MinioService
{
    public Dictionary<string, byte[]> Objects { get; } = new();
    public List<string> Requested { get; } = new();

    public FakeMinioService() : base(null!, new ConfigurationBuilder().Build()) { }

    public override Task<byte[]?> ReadObjectAsync(string objectName)
    {
        Requested.Add(objectName);
        return Task.FromResult(Objects.TryGetValue(objectName, out var bytes) ? bytes : null);
    }
}
