using ef;
using Microsoft.EntityFrameworkCore;
using Xunit;

public class ProjectServiceTests
{
    private CodeDbContext CreateDb()
    {
        var options = new DbContextOptionsBuilder<CodeDbContext>()
            .UseInMemoryDatabase(Guid.NewGuid().ToString())
            .Options;

        return new CodeDbContext(options);
    }

    [Fact]
    public async Task AddProjectAsync_ShouldCreateProject_WhenInvestigationExists()
    {
        // Arrange
        var db = CreateDb();

        db.Investigations.Add(new DbInvestigation
        {
            ID = 1,
            Name = "Investigation",
            Description="Description"
        });

        await db.SaveChangesAsync();

        var service = new ProjectService(db);

        var data = new ProjectData
        (
            1,
           "Test Project",
            "Description"
        );

        // Act
        var result = await service.AddProjectAsync(data);

        // Assert
        Assert.True(result.Ok);

        var project = await db.Projects.FirstOrDefaultAsync();

        Assert.NotNull(project);
        Assert.Equal("Test Project", project.Name);
        Assert.Equal(1, project.InvestigationID);
    }
    [Fact]
    public async Task AddProjectAsync_ShouldFail_WhenInvestigationDoesNotExist()
    {
        var db = CreateDb();

        var service = new ProjectService(db);

        var data = new ProjectData
        (
             999,
           "Project",
            "Desc"
        );

        var result = await service.AddProjectAsync(data);

        Assert.False(result.Ok);
    }
    [Fact]
    public async Task GetProjectsAsync_ShouldReturnProjectsOfInvestigation()
    {
        var db = CreateDb();

        db.Investigations.Add(new DbInvestigation
        {
            ID = 1,
            UserID = 1,
            Name = "Inv",
            Description="Description"
        });

        db.Projects.Add(new DbProject
        {
            ID = 1,
            InvestigationID = 1,
            Name = "Project1",
            Description="Description"
        });

        db.Projects.Add(new DbProject
        {
            ID = 2,
            InvestigationID = 1,
            Name = "Project2",
            Description="Description"
        });

        await db.SaveChangesAsync();

        var service = new ProjectService(db);

        var result = await service.GetProjectsAsync(
            new InvestigationID(1));
        

        Assert.True(result.Ok);

        var projects = Assert.IsType<List<Project>>(result.Data);

        Assert.Equal(2, projects.Count);
    }
    [Fact]
    public async Task DeleteProjectAsync_ShouldDeleteProject()
    {
        var db = CreateDb();

        db.Projects.Add(new DbProject
        {
            ID = 1,
            Name = "Project",
            Description="Description"
        });

        await db.SaveChangesAsync();

        var service = new ProjectService(db);

        var result = await service.DeleteProjectAsync(
            new Id(1)
        );

        Assert.True(result.Ok);

        Assert.Empty(db.Projects);
    }
}