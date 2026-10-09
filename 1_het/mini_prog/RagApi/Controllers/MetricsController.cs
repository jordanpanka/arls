using System.Threading.Tasks;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;

[ApiController]
[Route("/api/projects/{projectId:int}/metrics")]
public class MetricsController : ControllerBase
{
    private readonly MetricsService metricsService;
    private readonly MetricsAnalysisService analysisService;

    public MetricsController(MetricsService metrics, MetricsAnalysisService analysis)
    {
        metricsService = metrics;
        analysisService = analysis;
    }

    [Authorize]
    [HttpPost("analyze")]
    public async Task<IActionResult> Analyze(int projectId, [FromBody] AnalyzeMetricsRequest? request)
    {
        if (!TryGetUserId(out var userId)) return Unauthorized();

        var result = await analysisService.QueueAsync(userId, projectId, request?.force ?? false);
        return result.Status == MetricsLookupStatus.Found ? Accepted(result.Data) : ToError(result.Status);
    }

    [Authorize]
    [HttpGet("status")]
    public async Task<IActionResult> Status(int projectId)
    {
        if (!TryGetUserId(out var userId)) return Unauthorized();
        return ToResult(await metricsService.GetStatusAsync(userId, projectId));
    }

    [Authorize]
    [HttpGet]
    public async Task<IActionResult> Repository(int projectId)
    {
        if (!TryGetUserId(out var userId)) return Unauthorized();
        return ToResult(await metricsService.GetRepositoryMetricsAsync(userId, projectId));
    }

    [Authorize]
    [HttpGet("files")]
    public async Task<IActionResult> Files(int projectId, [FromQuery] string? sort, [FromQuery] bool desc = true, [FromQuery] int? limit = null)
    {
        if (!TryGetUserId(out var userId)) return Unauthorized();
        return ToResult(await metricsService.GetFileMetricsAsync(userId, projectId, sort, desc, limit));
    }

    [Authorize]
    [HttpGet("files/detail")]
    public async Task<IActionResult> FileDetail(int projectId, [FromQuery] string path)
    {
        if (!TryGetUserId(out var userId)) return Unauthorized();
        if (string.IsNullOrWhiteSpace(path)) return BadRequest("A file path is required.");
        return ToResult(await metricsService.GetFileDetailAsync(userId, projectId, path));
    }

    [Authorize]
    [HttpGet("functions")]
    public async Task<IActionResult> Functions(int projectId, [FromQuery] string? path, [FromQuery] string? sort, [FromQuery] int? limit = null)
    {
        if (!TryGetUserId(out var userId)) return Unauthorized();
        return ToResult(await metricsService.GetFunctionMetricsAsync(userId, projectId, path, sort, limit));
    }

    [Authorize]
    [HttpGet("hotspots/{kind}")]
    public async Task<IActionResult> Hotspots(int projectId, string kind, [FromQuery] int? limit = null)
    {
        if (!TryGetUserId(out var userId)) return Unauthorized();

        return kind.ToLowerInvariant() switch
        {
            "complexity" => ToResult(await metricsService.GetComplexityHotspotsAsync(userId, projectId, limit)),
            "dependencies" => ToResult(await metricsService.GetDependencyHotspotsAsync(userId, projectId, limit)),
            "maintainability" => ToResult(await metricsService.GetMaintainabilityHotspotsAsync(userId, projectId, limit)),
            _ => NotFound("Unknown hotspot kind. Use complexity, dependencies or maintainability."),
        };
    }

    private bool TryGetUserId(out int userId)
    {
        userId = 0;
        var uidClaim = User.FindFirst("uid")?.Value;
        return uidClaim != null && int.TryParse(uidClaim, out userId);
    }

    private IActionResult ToResult<T>(MetricsLookup<T> lookup) =>
        lookup.Status == MetricsLookupStatus.Found ? Ok(lookup.Data) : ToError(lookup.Status);

    private IActionResult ToError(MetricsLookupStatus status) => status switch
    {
        MetricsLookupStatus.Forbidden => StatusCode(StatusCodes.Status403Forbidden, new { error = "forbidden", message = "You don't have access to this project." }),
        MetricsLookupStatus.ProjectNotFound => NotFound(new { error = "project_not_found", message = "The project doesn't exist." }),
        MetricsLookupStatus.NoAnalysis => NotFound(new { error = "no_analysis", message = "No code metrics analysis has been run for this repository." }),
        _ => NotFound(new { error = "not_found", message = "No metrics were found for this item." }),
    };
}
