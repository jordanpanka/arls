using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;
using ef;
using Microsoft.AspNetCore.Http;
using Microsoft.EntityFrameworkCore;
using UglyToad.PdfPig;
using System.Net.Http.Headers;
public class FileService
{
    private readonly CodeDbContext codeDbContext;
    private readonly HttpClient httpClient;
    private readonly IConfiguration configuration;

    public FileService(CodeDbContext cdb, HttpClient http, IConfiguration iconf)
    {
        codeDbContext = cdb;
        httpClient=http;
        configuration=iconf;
    }
    private string NormalizeRelativePath(string path)
    {
        path = path.Replace("\\", "/").Trim();

        while (path.StartsWith("/"))
            path = path[1..];

        if (path.Contains(".."))
            throw new Exception("Invalid relative path.");

        return path;
    }
    public async Task<ServiceResult> UploadAsync(int pid, List<IFormFile> files, List<string> paths)
    {
        if (files.Count == 0 || paths.Count == 0)
            return ServiceResult.Fail("Files and paths count doesn't exist.");

        if (files.Count != paths.Count)
        {
            return ServiceResult.Fail("The number of files and paths doesn1t match.");
        }
        var projexist = await codeDbContext.Projects.AnyAsync(x => x.ID == pid);
        if (!projexist) return ServiceResult.Fail("The project doesn't exist.");

        for (int i = 0; i < files.Count; i++)
        {
            var file = files[i];
            var relativePath = string.IsNullOrWhiteSpace(paths[i]) ? file.FileName : paths[i];

            if (file.FileName.EndsWith(".zip", StringComparison.OrdinalIgnoreCase))
            {
                var response = await SaveFileAsZip(pid, file, relativePath);
                if (!response.Ok) return ServiceResult.Fail("");
            }
            else
            {
                var response = await SaveFileAsNormal(pid, file, relativePath);
                if (!response.Ok) return ServiceResult.Fail("");
            }
        }
        await codeDbContext.SaveChangesAsync();
        return ServiceResult.Success();
    }

    /*public async Task<ServiceResult> CheckDuplicates(int userId, int investigationId, int projectId, IFormFile file, string path)
    {
        var exist=await codeDbContext.Files.FirstOrDefaultAsync(f->f.ProjectID==projectId && paths==f.RelativePath && f.Name==file.FileName);
        if (exist!=null)
        {
            var exist=await codeDbContext.Projects.FirstOrDefaultAsync(f->f.ID==projectId && f.InvestigationID==investigationId);
            if (exist!=null)
            {
                var exist=await codeDbContext.Investigation.FirstOrDefaultAsync(f->f.ID==investigationId && f.UserID==userId);
                if (exist != null)
                {
                    return ServiceResult.Fail("File already exist.")
                }
                else
                {
                    return ServiceResult.Success();
                }
            }
            else
            {
                return ServiceResult.Success();
            }
        }
        else
        {
            return ServiceResult.Success();
        }
    }*/
    public async Task<ServiceResult> CheckDuplicates( int userId,int investigationId,int projectId,IFormFile file,string path)
    {
        var exists = await codeDbContext.Files.AnyAsync(f =>
            f.ProjectID == projectId &&
            f.RelativePath == path &&
            f.Name == file.FileName &&
            f.Project.InvestigationID == investigationId &&
            f.Project.Investigation.UserID == userId
        );

        if (exists)
        {
            return ServiceResult.Fail("File already exists.");
        }

        return ServiceResult.Success();
    }

   
    public async Task<HashSet<string>> GetStoredFileKeysAsync(int userId, int investigationId, int projectId)
    {
        var stored = await codeDbContext.Files
            .Where(f =>
                f.ProjectID == projectId &&
                f.Project.InvestigationID == investigationId &&
                f.Project.Investigation.UserID == userId)
            .Select(f => new { f.RelativePath, f.Name })
            .ToListAsync();

        return stored.Select(s => StoredFileKey(s.RelativePath, s.Name)).ToHashSet();
    }

    
    public static string StoredFileKey(string relativePath, string name) => $"{relativePath}\n{name}";
    public async Task<ServiceResult> SaveFileAsZip(int pid, IFormFile file, string path)
    {
        using var archive = new ZipArchive(file.OpenReadStream(), ZipArchiveMode.Read);

        foreach (var entry in archive.Entries)
        {
            if (string.IsNullOrWhiteSpace(entry.Name))
                continue;

            var entryRelativePath = NormalizeRelativePath(entry.FullName);
            var extension = Path.GetExtension(entry.Name);
            //var storedName = $"{Guid.NewGuid()}{extension}";

            var dbFile = new DbFile
            {
                ProjectID = pid,
                Name = entry.Name,
                RelativePath = entryRelativePath,
                StoragePath = "",
                Extension = extension,
                ContentType = file.ContentType ?? "",
                Size = entry.Length
            };

            codeDbContext.Files.Add(dbFile);
        }
        return ServiceResult.Success();

    }
    public async Task<ServiceResult> SaveFileAsNormal(int pid, IFormFile file, string path)
    {
        var fileSave = new DbFile { ProjectID = pid, Name = file.FileName, RelativePath = NormalizeRelativePath(path), StoragePath = "", Size = file.Length, ContentType = file.ContentType, Extension = Path.GetExtension(file.FileName) };
        codeDbContext.Files.Add(fileSave);
        return ServiceResult.Success();
    }
    static string ExtractTextFromPdf(IFormFile file)
    {
        using var ms = new MemoryStream();
        file.CopyTo(ms);
        ms.Position = 0;

        var sb = new StringBuilder();

        using (var pdf = PdfDocument.Open(ms))
        {
            foreach (var page in pdf.GetPages())
            {
                sb.AppendLine(page.Text);
            }
        }

        return sb.ToString();
    }
    static string ExtractTextFromDocx(IFormFile file)
    {
        using var ms = new MemoryStream();
        file.CopyTo(ms);
        ms.Position = 0;

        using var doc = WordprocessingDocument.Open(ms, false);
        var body = doc.MainDocumentPart?.Document?.Body;

        if (body is null) return "";

        // Body.InnerText egyszerű, de működik: összefűzi a szöveget
        return body.InnerText;
    }
    static List<string> chunkText(string text, int chunkLength, int redundance)
    {
        var list = new List<string>();
        int i = 0;
        while (i < text.Length)
        {
            int len = Math.Min(chunkLength, text.Length - i);
            var chunk = text.Substring(i, len);
            list.Add(chunk);
            i += chunkLength - redundance;
            if (chunkLength - redundance <= 0) break;
        }
        return list;
    }
    private async Task<float[]> Embed(HttpClient http, string text)
    {

        var payload = new { model = configuration["AI:EmbedModel"], prompt = text };
        var response = await http.PostAsJsonAsync($"{configuration["AI:QdrantUrl"]}/api/embeddings", payload);
        response.EnsureSuccessStatusCode();

        using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        return doc.RootElement.GetProperty("embedding")
           .EnumerateArray()
           .Select(x => x.GetSingle())
           .ToArray();
    }
    public async Task<ServiceResult> UploadQdrantAsync(int userId,List<IFormFile> files, Ids data)
    {
        foreach (var document in files)
        {
            string text = "";

            if (document is null || document.Length == 0)
                return ServiceResult.Fail("File is empty");

            var docName = Path.GetFileName(document.FileName);
            var ext = Path.GetExtension(docName).ToLowerInvariant();
            //document->string
            if (ext == ".txt")
            {
                using var reader = new StreamReader(document.OpenReadStream(), Encoding.UTF8, detectEncodingFromByteOrderMarks: true);
                text = await reader.ReadToEndAsync();
            }
            else if (ext == ".pdf")
            {
                text = ExtractTextFromPdf(document);
            }
            else if (ext == ".docx")
            {

            }
            else
            {
                return ServiceResult.Fail(".pdf or .txt required");
            }
            if (string.IsNullOrWhiteSpace(text))
                return ServiceResult.Fail("Nem sikerült szöveget kinyerni a fájlból (lehet, hogy szkennelt PDF).");

            //Text -> chunks
            var chunk = chunkText(text, 800, 170);

            //Chunks -> vector
            var points = new List<object>();
            for (int i = 0; i < chunk.Count; i++)
            {
                var point = await Embed(httpClient, chunk[i]);
                points.Add(new
                {
                    id = Guid.NewGuid().ToString(),
                    vector = point,
                    payload = new
                    {
                        userId=userId,
                        investigationId=data.invId,
                        projectId=data.projectId,
                        docName = document.Name,
                        chunkText = i,
                        text = chunk[i]
                    }
                });
            }
            //chunks -> qdrant
            var upsertPayload = new { points };
            var upsertRes = await httpClient.PutAsJsonAsync($"{configuration["AI:QdrantUrl"]}/collections/{configuration["AI:Collection"]}/points?wait=true", upsertPayload);
            upsertRes.EnsureSuccessStatusCode();

            //return ServiceResult.Success(new { uploaded = docName, chunks = chunk.Count });

        }
        return ServiceResult.Success();
    }
    

public async Task<ServiceResult> UploadQdrantPythonAsync(int userId, List<IFormFile> files,List<string> paths, int projectId, int invId)
{
    try
    {

        using var content = new MultipartFormDataContent();

        content.Add(new StringContent(userId.ToString()), "user_id");
        content.Add(new StringContent(invId.ToString()), "inv_id");
        content.Add(new StringContent(projectId.ToString()), "project_id");

        foreach (var file in files)
        {
            if (file == null || file.Length == 0)
                return ServiceResult.Fail("File is empty");

            var stream = file.OpenReadStream();
            var fileContent = new StreamContent(stream);

            if (!string.IsNullOrWhiteSpace(file.ContentType))
            {
                fileContent.Headers.ContentType = new MediaTypeHeaderValue(file.ContentType);
            }

            content.Add(fileContent, "files", file.FileName);
        }
        foreach (var path in paths)
        {
            content.Add(new StringContent(path), "paths");
        }

        var pythonUrl = $"{configuration["AI:PythonUrl"]}/api/chat/files/upload";

        var response = await httpClient.PostAsync(pythonUrl, content);
        var responseBody = await response.Content.ReadAsStringAsync();

        if (!response.IsSuccessStatusCode)
        {
            return ServiceResult.Fail($"Python service error: {responseBody}");
        }

        return ServiceResult.Success(responseBody);
    }
    catch (Exception ex)
    {
        return ServiceResult.Fail($"Python upload failed: {ex.Message}");
    }
}
}