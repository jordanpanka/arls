using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using DocumentFormat.OpenXml.Drawing.Diagrams;
using ef;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Internal;
using UglyToad.PdfPig.Graphics.Colors;

public class ProjectService
{
     private readonly CodeDbContext codeDbContext;

     public ProjectService(CodeDbContext db)
    {
        codeDbContext=db;
    }
    public async Task<ServiceResult> AddInvAsync(int userId,InvestigationData data)
    {
        //user exist?
        var exist=await codeDbContext.Users.AnyAsync(x=>x.ID==userId);

        if(!exist) return ServiceResult.Fail("User doesn't exist");

        var inv=new DbInvestigation{UserID=userId,Name=data.name, Description=data.description};

        codeDbContext.Investigations.Add(inv);
        await codeDbContext.SaveChangesAsync();
        return ServiceResult.Success();
    }
    public async Task<ServiceResult> AddProjectAsync(ProjectData data)
    {
        //
        var exist=await codeDbContext.Investigations.AnyAsync(x=>x.ID==data.invid);
        if(!exist) return ServiceResult.Fail("Investigation doesn't exist");

        var project=new DbProject{InvestigationID=data.invid,Name=data.name,Description=data.description};
        codeDbContext.Projects.Add(project);
        await codeDbContext.SaveChangesAsync();
        return ServiceResult.Success();
    } 
    public async Task<ServiceResult> AddFilesAsync(FilesData data)
    {
        var exist=await codeDbContext.Projects.AnyAsync(x=>x.ID==data.projectId);
        if(!exist) return ServiceResult.Fail("Project doesn't exist");

        var file=new DbFile{};

        codeDbContext.Files.Add(file);
        await codeDbContext.SaveChangesAsync();
        return ServiceResult.Success();
    }
    public async Task<ServiceResult> GetInvestigationsAsync(int data)
    {
        var exist=await codeDbContext.Users.AnyAsync(x=>x.ID==data);
        if(!exist) return ServiceResult.Fail("User doesn't exist");

        var investigations=await codeDbContext.Investigations
        .Where(x=>x.UserID==data)
        .Select(x=>new Investigation
        {
            ID=x.ID,
            Name=x.Name,
            Description=x.Description
        })
        .ToListAsync();

        return ServiceResult.Success(investigations);
    }
    public async Task<ServiceResult> GetProjectsAsync(InvestigationID data)
    {
        var exist=await codeDbContext.Investigations.AnyAsync(x=>x.ID==data.id);
        if(!exist) return ServiceResult.Fail("Investigation doesn't exist");

        var projects=await codeDbContext.Projects
        .Where(x=>x.InvestigationID==data.id)
        .Select(x=>new Project
        {
            ID=x.ID,
            Name=x.Name,
            Description=x.Description
        })
        .ToListAsync();

        return ServiceResult.Success(projects);
    }

    public async Task<ServiceResult> GetFilesAsync(ProjectID data)
    {
        var exist=await codeDbContext.Projects.AnyAsync(x=>x.ID==data.id);
        if(!exist) return ServiceResult.Fail("Project doesn't exist");

        var files=await codeDbContext.Files
        .Where(x=>x.ProjectID==data.id)
        .Select(x=>new File
        {
            ID=x.ID,
            Name=x.Name,
            RelativePath=x.RelativePath
        })
        .ToListAsync();

        return ServiceResult.Success(files);
    }
    public async Task<ServiceResult> DeleteInvestigationsAsync(int invid)
    {
        var exist=await codeDbContext.Investigations.SingleOrDefaultAsync(x=>x.ID==invid);
        if(exist==null) return ServiceResult.Fail("Investigation doesn't exist");

        codeDbContext.Investigations.Remove(exist);
        await codeDbContext.SaveChangesAsync();
        return ServiceResult.Success();
    }

    public async Task<ServiceResult> DeleteProjectAsync(Id data)
    {
        var exist= await codeDbContext.Projects.SingleOrDefaultAsync(x=>x.ID==data.id);
        if(exist==null) return ServiceResult.Fail("Project doesn't exist");

        codeDbContext.Projects.Remove(exist);
        await codeDbContext.SaveChangesAsync();
        return ServiceResult.Success();
    }

    public async Task<ServiceResult> RenameInvestigationAsync(RenameData data)
    {
        var exist=await codeDbContext.Investigations.SingleOrDefaultAsync(x=>x.ID==data.id);
        if(exist==null) return ServiceResult.Fail("Investigation doesn't exist");

        exist.Name=data.name;
        await codeDbContext.SaveChangesAsync();
        return ServiceResult.Success();

    }
    public async Task<ServiceResult> RenameProjectAsync(RenameData data)
    {
        var exist=await codeDbContext.Projects.SingleOrDefaultAsync(x=>x.ID==data.id);
        if(exist==null) return ServiceResult.Fail("Project doesn't exist");

        exist.Name=data.name;
        await codeDbContext.SaveChangesAsync();
        return ServiceResult.Success();
    }
}