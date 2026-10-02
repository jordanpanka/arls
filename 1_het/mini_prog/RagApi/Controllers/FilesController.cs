using System.Collections.Generic;
using System.Threading.Tasks;
using Azure;
using ef;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using UglyToad.PdfPig.Graphics.Colors;
[ApiController]
[Route("/api/investigations/projects/files")]
public class FilesController : ControllerBase
{
    private readonly FileService filesService;
    private readonly MinioService minioService;

    public FilesController(FileService fs, MinioService ms)
    {
        filesService=fs;
        minioService=ms;
    }
    [Authorize]
    [HttpPost("upload")]
    public async Task<IActionResult> UploadFile( [FromForm] List<IFormFile> files,
    [FromForm] List<string> paths,  [FromForm] int invId,[FromForm] int projectId)
    {   
        var uidClaim = User.FindFirst("uid")?.Value;
        if (uidClaim == null) return Unauthorized();
        
        var newFileList=new List<IFormFile>();
        var newFilePath=new List<String>();
        for(int i = 0; i<files.Count;i++)
        {
            var resp=await filesService.CheckDuplicates(int.Parse(uidClaim),invId,projectId, files[i],paths[i]);
            if(resp.Ok){ 
                newFileList.Add(files[i]);
                newFilePath.Add(paths[i]);
            }
        }
        if(newFileList.Count==0) return BadRequest("File/files with this name already uploaded.");
        //var resp=await filesService.CheckDuplicates(uidClaim,)
        var result = await filesService.UploadQdrantPythonAsync(int.Parse(uidClaim), newFileList,newFilePath, projectId, invId);
        if (!result.Ok) return BadRequest(result.Error);

        var response=await filesService.UploadAsync(projectId,newFileList,newFilePath);
        if(!response.Ok) return BadRequest();

        //response??? minden ok?
        await minioService.UploadAsync(int.Parse(uidClaim),newFileList,newFilePath,projectId, invId);

        return Ok();

    }

    [Authorize]
    [HttpGet("/api/projects/{projectId:int}/files/{fileId:int}")]
    public async Task<IActionResult> GetFileContent(int projectId, int fileId)
    {
        var uidClaim = User.FindFirst("uid")?.Value;
        if (uidClaim == null || !int.TryParse(uidClaim, out var userId)) return Unauthorized();

        var lookup = await filesService.FindProjectFileAsync(userId, projectId, fileId);
        switch (lookup.Status)
        {
            case FileLookupStatus.Forbidden:
                return StatusCode(StatusCodes.Status403Forbidden, "You don't have access to this project.");
            case FileLookupStatus.ProjectNotFound:
            case FileLookupStatus.FileNotFound:
                return NotFound("The file doesn't exist in this project.");
        }

        var file = lookup.File!;
        var bytes = await minioService.ReadObjectAsync(
            MinioService.ObjectName(lookup.OwnerId, lookup.InvestigationId, projectId, file.RelativePath));

        if (bytes == null) return NotFound("The original file is no longer in storage.");

        if (Array.IndexOf(bytes, (byte)0, 0, Math.Min(bytes.Length, 8000)) >= 0)
            return StatusCode(StatusCodes.Status415UnsupportedMediaType, "This file type can't be previewed.");

        using var reader = new StreamReader(new MemoryStream(bytes), System.Text.Encoding.UTF8, detectEncodingFromByteOrderMarks: true);
        var content = await reader.ReadToEndAsync();

        return Ok(new ProjectFileContent(
            file.ID.ToString(),
            file.Name,
            file.RelativePath,
            SourceLanguage.FromPath(file.RelativePath),
            content));
    }

}
