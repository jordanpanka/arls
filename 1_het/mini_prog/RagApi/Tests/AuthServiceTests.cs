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

    private async Task<(CodeDbContext db, AuthService service, int userId)> CreateUserAsync(string password)
    {
        var db = CreateDb();
        var service = new AuthService(db, null!);
        await service.RegisterAsync(new RegisterData("test@test.com", password, "Teszt", "Elek"));
        var user = await db.Users.SingleAsync();
        return (db, service, user.ID);
    }

    [Fact]
    public async Task ChangePasswordAsync_ShouldUpdatePassword_WhenCurrentPasswordIsCorrect()
    {
        var (db, service, userId) = await CreateUserAsync("Password123");

        var result = await service.ChangePasswordAsync(userId, new ChangePasswordData("Password123", "NewPassword456"));

        Assert.True(result.Ok);

        var user = await db.Users.SingleAsync();

        Assert.True(service.VerifyPassword("NewPassword456", user.Passwordsalt, user.PasswordHash));
        Assert.False(service.VerifyPassword("Password123", user.Passwordsalt, user.PasswordHash));
    }

    [Fact]
    public async Task ChangePasswordAsync_ShouldFail_WhenCurrentPasswordIsWrong()
    {
        var (db, service, userId) = await CreateUserAsync("Password123");

        var result = await service.ChangePasswordAsync(userId, new ChangePasswordData("WrongPassword", "NewPassword456"));

        Assert.False(result.Ok);
        Assert.Equal("Hibás a jelenlegi jelszó", result.Error);

        var user = await db.Users.SingleAsync();

        Assert.True(service.VerifyPassword("Password123", user.Passwordsalt, user.PasswordHash));
    }

    [Fact]
    public async Task ChangePasswordAsync_ShouldFail_WhenNewPasswordIsTooWeak()
    {
        var (_, service, userId) = await CreateUserAsync("Password123");

        var result = await service.ChangePasswordAsync(userId, new ChangePasswordData("Password123", "weak"));

        Assert.False(result.Ok);
    }

    [Fact]
    public async Task ChangePasswordAsync_ShouldFail_WhenNewPasswordEqualsCurrent()
    {
        var (_, service, userId) = await CreateUserAsync("Password123");

        var result = await service.ChangePasswordAsync(userId, new ChangePasswordData("Password123", "Password123"));

        Assert.False(result.Ok);
        Assert.Equal("Az új jelszó nem egyezhet meg a jelenlegivel.", result.Error);
    }

    [Fact]
    public async Task ChangePasswordAsync_ShouldFail_WhenUserDoesNotExist()
    {
        var db = CreateDb();
        var service = new AuthService(db, null!);

        var result = await service.ChangePasswordAsync(42, new ChangePasswordData("Password123", "NewPassword456"));

        Assert.False(result.Ok);
    }
}