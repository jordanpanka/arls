using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Configuration;

[ApiController]
[Route("/api/internal/projects/{projectId:int}/metrics")]
public class InternalMetricsController : ControllerBase
{
    public const string KeyHeader = "X-Internal-Key";

    private readonly MetricsService metricsService;
    private readonly IConfiguration configuration;

    public InternalMetricsController(MetricsService metrics, IConfiguration config)
    {
        metricsService = metrics;
        configuration = config;
    }

    [AllowAnonymous]
    [HttpPost("evidence")]
    public async Task<IActionResult> Evidence(int projectId, [FromBody] RagMetricsRequest request)
    {
        if (!HasValidKey()) return Unauthorized();

        var lookup = await metricsService.GetRagEvidenceAsync(projectId, request);
        return lookup.Status switch
        {
            MetricsLookupStatus.Found => Ok(lookup.Data),
            MetricsLookupStatus.Forbidden => StatusCode(StatusCodes.Status403Forbidden),
            _ => NotFound(new { available = false, error = lookup.Status.ToString() }),
        };
    }

    private bool HasValidKey()
    {
        var expected = configuration["Internal:ApiKey"];
        var provided = Request.Headers[KeyHeader].ToString();
        if (string.IsNullOrEmpty(expected) || string.IsNullOrEmpty(provided)) return false;

        return CryptographicOperations.FixedTimeEquals(Encoding.UTF8.GetBytes(expected), Encoding.UTF8.GetBytes(provided));
    }
}
