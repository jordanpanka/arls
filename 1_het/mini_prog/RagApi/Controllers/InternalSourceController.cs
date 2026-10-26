using System.Security.Cryptography;
using System.Text;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

public static class InternalKey
{
    public const string Header = "X-Internal-Key";

    public static bool IsValid(HttpRequest request, IConfiguration configuration)
    {
        var expected = configuration["Internal:ApiKey"];
        var provided = request.Headers[Header].ToString();
        if (string.IsNullOrEmpty(expected) || string.IsNullOrEmpty(provided)) return false;

        return CryptographicOperations.FixedTimeEquals(Encoding.UTF8.GetBytes(expected), Encoding.UTF8.GetBytes(provided));
    }
}

[ApiController]
[Route("/api/internal/projects/{projectId:int}/source")]
public class InternalSourceController : ControllerBase
{
    private readonly SourceAccessService sourceService;
    private readonly IConfiguration configuration;

    public InternalSourceController(SourceAccessService source, IConfiguration config)
    {
        sourceService = source;
        configuration = config;
    }

    [AllowAnonymous]
    [HttpPost("files")]
    public async Task<IActionResult> Files(int projectId, [FromBody] SourceFilesRequest request)
    {
        if (!InternalKey.IsValid(Request, configuration)) return Unauthorized();
        return ToResult(await sourceService.FilesAsync(projectId, request));
    }

    [AllowAnonymous]
    [HttpPost("content")]
    public async Task<IActionResult> Content(int projectId, [FromBody] SourceContentRequest request)
    {
        if (!InternalKey.IsValid(Request, configuration)) return Unauthorized();
        return ToResult(await sourceService.ContentAsync(projectId, request));
    }

    [AllowAnonymous]
    [HttpPost("search")]
    public async Task<IActionResult> Search(int projectId, [FromBody] SourceSearchRequest request)
    {
        if (!InternalKey.IsValid(Request, configuration)) return Unauthorized();
        return ToResult(await sourceService.SearchAsync(projectId, request, HttpContext.RequestAborted));
    }

    private IActionResult ToResult<T>(SourceLookup<T> lookup) => lookup.Status switch
    {
        SourceLookupStatus.Found => Ok(lookup.Data),
        SourceLookupStatus.Forbidden => StatusCode(StatusCodes.Status403Forbidden),
        SourceLookupStatus.Invalid => BadRequest(new { error = lookup.Error }),
        _ => NotFound(new { error = lookup.Error ?? lookup.Status.ToString() }),
    };
}
