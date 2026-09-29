using System.Threading.Tasks;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

[ApiController]
[Route("/api/investigations/projects/repositories")]
public class RepositoryController : ControllerBase
{
    private readonly RepositoryIngestService ingestService;

    public RepositoryController(RepositoryIngestService ingest)
    {
        ingestService = ingest;
    }

    [Authorize]
    [HttpPost("add")]
    public async Task<IActionResult> AddRepository([FromBody] AddRepositoryData data)
    {
        var uidClaim = User.FindFirst("uid")?.Value;
        if (uidClaim == null) return Unauthorized();

        if (string.IsNullOrWhiteSpace(data.owner) || string.IsNullOrWhiteSpace(data.repo))
            return BadRequest("Owner and repo are required.");

        var reference = string.IsNullOrWhiteSpace(data.reference) ? "HEAD" : data.reference;

        var result = await ingestService.QueueAsync(
            int.Parse(uidClaim), data.invId, data.projectId,
            data.owner, data.repo, reference);

        if (!result.Ok) return BadRequest(result.Error);

        return Accepted(result.Data);
    }

    [Authorize]
    [HttpPost("load")]
    public async Task<IActionResult> GetRepositories([FromBody] ProjectID data)
    {
        var uidClaim = User.FindFirst("uid")?.Value;
        if (uidClaim == null) return Unauthorized();

        var result = await ingestService.GetForProjectAsync(data.id);
        if (!result.Ok) return BadRequest(result.Error);
        return Ok(result.Data);
    }
}

public record AddRepositoryData(int invId, int projectId, string owner, string repo, string? reference);
