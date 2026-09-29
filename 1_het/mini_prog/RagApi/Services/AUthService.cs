using System.Net.Mail;
using System.Security.Cryptography;
using ef;
using Microsoft.AspNetCore.Http.HttpResults;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
public class AuthService
{
    private readonly CodeDbContext db;
     private readonly JwtService jwt;
     public AuthService(CodeDbContext cdb, JwtService jwts)
    {
        db = cdb;
        jwt = jwts;
    }
    public async Task<ServiceResult> RegisterAsync(RegisterData data)
    {
        if (string.IsNullOrEmpty(data.email)) return ServiceResult.Fail("Email cím megadása kötelező.");
        if (string.IsNullOrEmpty(data.email)) return ServiceResult.Fail("Jelszó megadása kötelező.");
        var email = data.email.Trim().ToLowerInvariant();
        if (!IsValidEmail(email)) return ServiceResult.Fail("Hibás email formátum.");
        if (string.IsNullOrWhiteSpace(data.password) || data.password.Length < 6)
            return ServiceResult.Fail("A jelszó nem felel meg a követelményeknek");

        if (!IsValidEmail(email)) return ServiceResult.Fail("Hibás email formátum.");

        if (string.IsNullOrWhiteSpace(data.password) || data.password.Length < 6 || !HasUpperAndLower(data.password))
            return ServiceResult.Fail("A jelszó nem felel meg a követelményeknek\n -tartalmaznia kell kis-és nagy betűt\n -legalább 6 karakter hosszú legyen\n");

        var exist = await db.Users.AnyAsync(x => x.Email == email);
        if (exist)
            return ServiceResult.Fail("Már létezik ez az email cím");

        var (salt, hash) = HashPassword(data.password);
        var user = new DbUser { Email = email, FirstName=data.firstName, LastName=data.lastName,PasswordHash = hash, Passwordsalt = salt, CreatedTime = DateTime.UtcNow };

        db.Users.Add(user);
        await db.SaveChangesAsync();
        return ServiceResult.Success();
    }
    public async Task<ServiceResult>LoginAsync(RegisterData data)
    {
        var email=data.email.Trim().ToLowerInvariant();
        var user=await db.Users.SingleOrDefaultAsync(x => x.Email==email);
        if(user==null)
            return ServiceResult.Fail("Nem létezik a megadott email cím!");

        if(!VerifyPassword(data.password,user.Passwordsalt, user.PasswordHash))
            return ServiceResult.Fail("Hibás a jelszó");

        var token=jwt.CreateToken(user);
        var response=new{FirstName=user.FirstName,LastName=user.LastName, Token=token};

        return ServiceResult.Success(response);
        
    }
    public (byte[] hash, byte[] salt) HashPassword(string pass)
    {
        var salt = RandomNumberGenerator.GetBytes(16);
        var hash = Rfc2898DeriveBytes.Pbkdf2(
            pass,
            salt,
            100_000,
            HashAlgorithmName.SHA256,
            32);

        return (salt, hash);

    }
    public bool VerifyPassword(string pass, byte[] salt,byte[] expectedHash)
    {
        var hash = Rfc2898DeriveBytes.Pbkdf2(
            pass,
            salt,
            100_000,
            HashAlgorithmName.SHA256,
            32);

        return CryptographicOperations.FixedTimeEquals(hash, expectedHash);
        
    }
    public bool IsValidEmail(string email)
    {
        try
        {
            var addr = new MailAddress(email);
            return addr.Address == email;
        }
        catch
        {
            return false;
        }
    }
    private bool HasUpperAndLower(string input)
    {
        return input.Any(char.IsUpper) && input.Any(char.IsLower);
    }
}