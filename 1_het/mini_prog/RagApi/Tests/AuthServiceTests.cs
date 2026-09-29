using ef;
using Microsoft.EntityFrameworkCore;
using Xunit;

public class AuthServiceTests
{
    private CodeDbContext CreateDb()
    {
        var options = new DbContextOptionsBuilder<CodeDbContext>()
            .UseInMemoryDatabase(Guid.NewGuid().ToString())
            .Options;

        return new CodeDbContext(options);
    }

    [Fact]
    public async Task RegisterAsync_ShouldCreateUser_WhenDataIsValid()
    {
        var db = CreateDb();
        var service = new AuthService(db, null!);

        var data = new RegisterData(
            "test@test.com",
            "Password123",
            "Teszt",
            "Elek"
        );

        var result = await service.RegisterAsync(data);

        Assert.True(result.Ok);

        var user = await db.Users.FirstOrDefaultAsync();

        Assert.NotNull(user);
        Assert.Equal("test@test.com", user.Email);
        Assert.Equal("Teszt", user.FirstName);
        Assert.Equal("Elek", user.LastName);
    }

    [Fact]
    public async Task RegisterAsync_ShouldFail_WhenEmailAlreadyExists()
    {
        var db = CreateDb();

        db.Users.Add(new DbUser
        {
            Email = "test@test.com",
            FirstName = "Teszt",
            LastName = "Elek",
            PasswordHash = new byte[] { 1, 2, 3 },
            Passwordsalt = new byte[] { 4, 5, 6 },
            CreatedTime = DateTime.UtcNow
        });

        await db.SaveChangesAsync();

        var service = new AuthService(db, null!);

        var data = new RegisterData(
            "test@test.com",
            "Password123",
            "Másik",
            "User"
        );

        var result = await service.RegisterAsync(data);

        Assert.False(result.Ok);
        Assert.Equal("Már létezik ez az email cím", result.Error);
    }

    [Fact]
    public async Task RegisterAsync_ShouldFail_WhenEmailFormatIsInvalid()
    {
        var db = CreateDb();
        var service = new AuthService(db, null!);

        var data = new RegisterData(
            "rossz-email",
            "Password123",
            "Teszt",
            "Elek"
        );

        var result = await service.RegisterAsync(data);

        Assert.False(result.Ok);
        Assert.Equal("Hibás email formátum.", result.Error);
    }

    [Fact]
    public async Task RegisterAsync_ShouldFail_WhenPasswordIsTooWeak()
    {
        var db = CreateDb();
        var service = new AuthService(db, null!);

        var data = new RegisterData(
            "test@test.com",
            "password",
            "Teszt",
            "Elek"
        );

        var result = await service.RegisterAsync(data);

        Assert.False(result.Ok);
    }

    [Fact]
    public void VerifyPassword_ShouldReturnTrue_WhenPasswordIsCorrect()
    {
        var db = CreateDb();
        var service = new AuthService(db, null!);

        var password = "Password123";

        var (salt, hash) = service.HashPassword(password);

        var result = service.VerifyPassword(password, salt, hash);

        Assert.True(result);
    }

    [Fact]
    public void VerifyPassword_ShouldReturnFalse_WhenPasswordIsWrong()
    {
        var db = CreateDb();
        var service = new AuthService(db, null!);

        var (salt, hash) = service.HashPassword("Password123");

        var result = service.VerifyPassword("WrongPassword", salt, hash);

        Assert.False(result);
    }
}