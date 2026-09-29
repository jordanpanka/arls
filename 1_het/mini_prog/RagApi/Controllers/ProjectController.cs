using System.Threading.Tasks;
using Azure;
using ef;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using UglyToad.PdfPig.Graphics.Colors;
[ApiController]
[Route("/api/investigations")]
public class ProjectController : ControllerBase
{
    //private readonly CodeDbContext codeDbContext;
    private readonly ProjectService projectService;
    public ProjectController(ProjectService ps)
    {
        projectService=ps;
    }
    [Authorize]
    [HttpPost("add")]
    public async Task<IActionResult> AddInvestigation([FromBody] InvestigationData inv)
    {
        var userId = int.Parse(User.FindFirst("uid")!.Value);
        var response = await projectService.AddInvAsync(userId, inv);
        if (!response.Ok) return BadRequest(response.Error);
        return Ok();
    }
    [Authorize]
    [HttpPost("projects/add")]
    public async Task<IActionResult> AddProject([FromBody] ProjectData data)
    {
        var uidClaim = User.FindFirst("uid");
        if (uidClaim == null) return Unauthorized("Missing uid claim");
        
        var response = await projectService.AddProjectAsync(data);
        if (!response.Ok) return BadRequest(response.Error);
        return Ok();
    }
    [Authorize]
    [HttpGet("projects/files/add")]
    public async Task<IActionResult> AddFiles([FromBody] FilesData data)
    {
        var response = await projectService.AddFilesAsync(data);
        if (!response.Ok) return BadRequest(response.Error);
        return Ok();
    }
    [Authorize]
    [HttpGet("load")]
    public async Task<IActionResult> GetInvestigations()
    {
        var uidClaim = User.FindFirst("uid");
        if (uidClaim == null) return Unauthorized("Missing uid claim");

        var userId = int.Parse(uidClaim.Value);

        var response = await projectService.GetInvestigationsAsync(userId);
        if (!response.Ok) return BadRequest(response.Error);
        return Ok(response.Data);
    }
    [Authorize]
    [HttpPost("projects/load")]
    public async Task<IActionResult> GetProjects([FromBody] InvestigationID data)
    {
        var uidClaim = User.FindFirst("uid");
        if (uidClaim == null) return Unauthorized("Missing uid claim");
        var response = await projectService.GetProjectsAsync(data);
        if (!response.Ok) return BadRequest(response.Error);
        return Ok(response.Data);
    }
    [Authorize]
    [HttpPost("projects/files/load")]
    public async Task<IActionResult> GetFiles([FromBody] ProjectID data)
    {
        var uidClaim = User.FindFirst("uid");
        if (uidClaim == null) return Unauthorized("Missing uid claim");
        var response = await projectService.GetFilesAsync(data);
        if (!response.Ok) return BadRequest(response.Error);
        return Ok(response.Data);
    }
    [Authorize]
    [HttpPost("delete")]
    public async Task<IActionResult> DeleteInvetigations([FromBody] ProjectID selectedInvId)
    {
        var uidClaim = User.FindFirst("uid");
        if (uidClaim == null) return Unauthorized("Missing uid claim");
        var response=await projectService.DeleteInvestigationsAsync(selectedInvId.id);
        if(!response.Ok) return BadRequest(response.Error);
        return Ok();
    }

    [Authorize]
    [HttpPost("projects/delete")]
    public async Task<IActionResult> DeleteProjects([FromBody] Id data)
    {
        var uidClaim = User.FindFirst("uid");
        if (uidClaim == null) return Unauthorized("Missing uid claim");

        var response= await projectService.DeleteProjectAsync(data);
        if(!response.Ok) return BadRequest(response.Error);
        return Ok();
    }

    [Authorize]
    [HttpPost("rename")]
    public async Task<IActionResult> RenameInvestigation([FromBody] RenameData data){

        var uidClaim=User.FindFirst("uid");
        if(uidClaim==null) return Unauthorized("Missing uid claim");

        var response=await projectService.RenameInvestigationAsync(data);
        if(!response.Ok)return BadRequest(response.Error);
        return Ok();
    }

    [Authorize]
    [HttpPost("projects/rename")]
    public async Task<IActionResult> RenameProject([FromBody] RenameData data)
    {
        var uidClaim=User.FindFirst("uid");
        if(uidClaim==null) return Unauthorized("Missing uid claim");

        var response=await projectService.RenameProjectAsync(data);
        if(!response.Ok) return BadRequest(response.Error);
        return Ok();

    }
    
}
