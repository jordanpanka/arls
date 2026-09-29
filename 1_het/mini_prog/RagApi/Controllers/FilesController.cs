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

}
