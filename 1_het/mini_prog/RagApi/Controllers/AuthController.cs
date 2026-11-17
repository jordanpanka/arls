using System.Threading.Tasks;
using ef;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
[ApiController]
[Route("/api/auth")]
    
public class AuthController : ControllerBase
{
    private readonly CodeDbContext codeDbContext;
    private readonly AuthService authService;

    public AuthController(CodeDbContext db, AuthService auth)
    {
        codeDbContext=db;
        authService=auth;
    }
    [HttpPost("register")]
    public async Task<IActionResult> Register([FromBody]RegisterData data)
    {
        var result=await authService.RegisterAsync(data);
        if(!result.Ok) return BadRequest(result.Error);
        return Ok();
    }
    [HttpPost("login")]
    public async Task<IActionResult> Login([FromBody] RegisterData data)
    {
        var result=await authService.LoginAsync(data);
        if(!result.Ok) return BadRequest(result.Error);
        return Ok(result.Data);
    }
    [Authorize]
    [HttpPost("change-password")]
    public async Task<IActionResult> ChangePassword([FromBody] ChangePasswordData data)
    {
        var uidClaim = User.FindFirst("uid")?.Value;
        if (uidClaim == null || !int.TryParse(uidClaim, out var userId)) return Unauthorized();

        var result=await authService.ChangePasswordAsync(userId, data);
        if(!result.Ok) return BadRequest(result.Error);
        return Ok();
    }
}