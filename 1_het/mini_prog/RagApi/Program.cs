using System.Text;
using System.Text.Json;
using UglyToad.PdfPig;
using DocumentFormat.OpenXml.Packaging;
using ef;
using Microsoft.EntityFrameworkCore;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.IdentityModel.Tokens;
using Microsoft.IdentityModel.Logging;
using Microsoft.AspNetCore.Builder;
using Microsoft.Extensions.DependencyInjection;
using System;
using Microsoft.Extensions.Configuration;
using System.Threading.Tasks;
using Minio;

var builder = WebApplication.CreateBuilder(args);
IdentityModelEventSource.ShowPII = true;

builder.Services.AddHttpClient("default", c =>
{
    c.Timeout = TimeSpan.FromMinutes(5);
});
builder.Services.AddDbContext<CodeDbContext>(options =>
    options.UseSqlServer(
        builder.Configuration.GetConnectionString("Default")
    ));
//JWt 
var jwtKey = builder.Configuration["Jwt:Key"];
var keyBytes = Encoding.UTF8.GetBytes(jwtKey!);
/*
builder.Services
    .AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
    .AddJwtBearer(options =>
    {
        options.TokenValidationParameters = new TokenValidationParameters
        {
            ValidateIssuer = true,
            ValidateAudience = true,
            ValidateLifetime = true,
            ValidateIssuerSigningKey = true,

            ValidIssuer = builder.Configuration["Jwt:Issuer"],
            ValidAudience = builder.Configuration["Jwt:Audience"],
            IssuerSigningKey = new SymmetricSecurityKey(keyBytes),

            ClockSkew = TimeSpan.FromMinutes(1)
        };
    });
*/
builder.Services
  .AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
  .AddJwtBearer(options =>
  {
      options.TokenValidationParameters = new TokenValidationParameters
      {
          ValidateIssuer = true,
          ValidateAudience = true,
          ValidateLifetime = true,
          ValidateIssuerSigningKey = true,

          ValidIssuer = builder.Configuration["Jwt:Issuer"],
          ValidAudience = builder.Configuration["Jwt:Audience"],
          IssuerSigningKey = new SymmetricSecurityKey(keyBytes),

          ClockSkew = TimeSpan.FromMinutes(1)
      };

      options.Events = new JwtBearerEvents
      {
          OnAuthenticationFailed = context =>
          {
              Console.WriteLine("JWT ERROR: " + context.Exception.Message);
              return Task.CompletedTask;
          }
      };
      options.Events = new JwtBearerEvents
      {
          OnMessageReceived = context =>
            {
                Console.WriteLine("RAW AUTH HEADER: " + context.Request.Headers.Authorization);
                return Task.CompletedTask;
            },
          OnAuthenticationFailed = context =>
            {
                Console.WriteLine("JWT ERROR: " + context.Exception);
                return Task.CompletedTask;
            }
      };
  });
builder.Services.AddSingleton<IMinioClient>(sp =>
{
    var config = sp.GetRequiredService<IConfiguration>();

    return new MinioClient()
        .WithEndpoint(config["Minio:Endpoint"] ?? "localhost:9000")
        .WithCredentials(
            config["Minio:AccessKey"] ?? "miniorag",
            config["Minio:SecretKey"] ?? "miniorag")
        .WithSSL(bool.TryParse(config["Minio:UseSsl"], out var ssl) && ssl)
        .Build();
});
builder.Services.AddAuthorization();
//add services
builder.Services.AddScoped<AuthService>();
builder.Services.AddScoped<JwtService>();
builder.Services.AddScoped<ProjectService>();

builder.Services.AddHttpClient<FileService>(c =>
{

    c.Timeout = TimeSpan.FromMinutes(60);
});

builder.Services.AddHttpClient<GitHubService>(c =>
{
    c.Timeout = TimeSpan.FromMinutes(10);
});
builder.Services.AddScoped<RepositoryIngestService>();

builder.Services.AddSingleton<RepositoryIngestQueue>();
builder.Services.AddHostedService<RepositoryIngestWorker>();
builder.Services.AddScoped<ChatService>();
builder.Services.AddScoped<MinioService>();


//controllers
builder.Services.AddControllers();

builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();

//preact,frontend
builder.Services.AddCors(options =>
{
    options.AddPolicy("frontend",
        policy =>
        {
            policy
                .WithOrigins("http://localhost:5173")
                .AllowAnyHeader()
                .AllowAnyMethod();
        });
});

var app = builder.Build();
app.UseSwagger();
app.UseSwaggerUI();
using (var scope = app.Services.CreateScope())
{
    var db = scope.ServiceProvider.GetRequiredService<CodeDbContext>();
    db.Database.Migrate();
}
/*app.MapGet("/", () => "RagApi fut ✅");*/

const string Qdrant = "http://localhost:6333";
const string Collection = "docs";
const string Ollama = "http://localhost:11434";
const string Embed_model = "embeddinggemma:latest";
const string Gen_model = "llama3";

static async Task EnsureCollection(HttpClient http, string qdrantUrl, string collection)
{
    var get = await http.GetAsync($"{qdrantUrl}/collections/{collection}");
    if (get.IsSuccessStatusCode) return;

    var createPayload = new
    {
        vectors = new
        {
            code = new
            {
                size = 768,
                distance = "Cosine"
            },
            summary = new
            {
                size = 768,
                distance = "Cosine"
            },
            text = new
            {
                size = 768,
                distance = "Cosine"
            }
        }
    };

    var create = await http.PutAsJsonAsync(
        $"{qdrantUrl}/collections/{collection}",
        createPayload
    );

    create.EnsureSuccessStatusCode();
}
app.Lifetime.ApplicationStarted.Register(() =>
{

    var qdrantUrl = app.Configuration["Ai:QdrantUrl"] ?? Qdrant;
    var qdrantCollection = app.Configuration["Ai:Collection"] ?? Collection;
    var logger = app.Services.GetRequiredService<ILogger<Program>>();

    _ = Task.Run(async () =>
    {
    
        try
        {
            using var scopeHttp = new HttpClient();
            await EnsureCollection(scopeHttp, qdrantUrl, qdrantCollection);
            logger.LogInformation(
                "Qdrant collection '{Collection}' ready at {Url}",
                qdrantCollection, qdrantUrl);
        }
        catch (Exception ex)
        {
            logger.LogError(ex,
                "Failed to ensure Qdrant collection '{Collection}' at {Url}",
                qdrantCollection, qdrantUrl);
        }
    });
});

/*
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
static async Task<float[]> Embed(HttpClient http, string text)
{
    
    var payload = new { model = Embed_model, prompt = text };
    var response = await http.PostAsJsonAsync($"{Ollama}/api/embeddings", payload);
    response.EnsureSuccessStatusCode();

    using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
    return doc.RootElement.GetProperty("embedding")
       .EnumerateArray()
       .Select(x => x.GetSingle())
       .ToArray();
}

//
app.MapPost("api/register", async (CodeDbContext db,RegisterData data) =>
{
    var email=data.email.Trim().ToLowerInvariant();
    if(data.password.IsNullorWhiteSpace() || data.password.Length<6)
        return Results.BadRequest("A jelszó nem felel meg a követelményeknek");
    
    var exist=db.Users.Where(x =>x.email==email);
    if(exist) return Results.BadRequest("Már létezik ez az email cím");

    var (salt, hash)=HasPassword(data.password);
    var user=new{ Email=email, PasswordHash=hash, PasswordSalt=salt, CreatedTime=DateTime.UtcNow};

    db.Users.Add(user);
    db.SaveChanges();
    return Results.Ok();

});/*
app.MapPost("/api/docs", async (HttpClient http, IFormFile document) =>
{
    string text="";

    if (document is null || document.Length == 0)
        return Results.BadRequest("Nincs fájl");

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
        return Results.BadRequest("Csak .pdf vagy .txt támogatott");
    }

    if (string.IsNullOrWhiteSpace(text))
        return Results.BadRequest("Nem sikerült szöveget kinyerni a fájlból (lehet, hogy szkennelt PDF).");

    //Text -> chunks
    var chunk = chunkText(text, 800, 170);

    //Chunks -> vector
    var points = new List<object>();
    for (int i = 0; i < chunk.Count; i++)
    {
        var point = await Embed(http, chunk[i]);
        points.Add(new
        {
            id = Guid.NewGuid().ToString(),
            vector = point,
            payload = new
            {
                docName = document.Name,
                chunkText = i,
                text = chunk[i]
            }
        });
    }
    //chunks -> qdrant
    var upsertPayload = new { points };
    var upsertRes = await http.PutAsJsonAsync($"{Qdrant}/collections/{Collection}/points?wait=true", upsertPayload);
    upsertRes.EnsureSuccessStatusCode();

    return Results.Ok(new { uploaded = docName, chunks = chunk.Count });

}).DisableAntiforgery();

app.MapPost("/api/chat", async (HttpClient http, ChatRequest req) =>
{
    http.Timeout = TimeSpan.FromMinutes(5);
    try{
    //text -> embedding
    var vec = await Embed(http, req.Prompt);

    //search with qdrant (top 5)
    var searchPayload = new
    {
        vector = vec,
        limit = 3,
        with_payload = true

    };
    var searchRes = await http.PostAsJsonAsync($"{Qdrant}/collections/{Collection}/points/search", searchPayload);
    searchRes.EnsureSuccessStatusCode();

    using var searchDoc = JsonDocument.Parse(await searchRes.Content.ReadAsStringAsync());
    var results = searchDoc.RootElement.GetProperty("result").EnumerateArray().ToList();
    
    Console.WriteLine("A találatok száma:"+results.Count);
        if (results.Count == 0)
        {
            return Results.Ok(new{answer="Nem találom a dokumentumokban."});
        }
    //making context
    var contextParts = new List<string>();
    foreach (var r in results)
    {
        var payload = r.GetProperty("payload");
        var text = payload.GetProperty("text").GetString() ?? " ";
        var docName = payload.GetProperty("docName").GetString() ?? "doc";
        var idx = payload.GetProperty("chunkText").GetInt32();
        contextParts.Add($"[Forrás: {docName} #{idx}]\n{text}");
    }
    var context = string.Join("\n\n---\n\n", contextParts);

    //prompt to model
    var finalPrompt = $"""
    Te egy asszisztens vagy, aki KIZÁRÓLAG az alábbi KONTEKSZTUS alapján válaszol.Mindig azon a nyelven válaszolj, amilyen nyelven a kérdés elhangzott. A szavak közé tegyél szóközöket, ha kell, úgy higy értelmesen legyenek elválasztva.Ha a válasz nem található a kontextusban, mondd: "Nem találom a dokumentumokban."

    KONTEKSZTUS:
    {context}

    KÉRDÉS:
    { req.Prompt}
    """;
   
    //Ollama generate
    var genPayload = new { model = Gen_model, prompt = finalPrompt, stream = false };
    var genRes = await http.PostAsJsonAsync($"{Ollama}/api/generate", genPayload);
    genRes.EnsureSuccessStatusCode();
    
    using var genDoc = JsonDocument.Parse(await genRes.Content.ReadAsStringAsync());
    var answer = genDoc.RootElement.GetProperty("response").GetString() ?? " ";
    //return Results.Ok(new{answer="Nem találom a dokumentumokban.1"});
    Console.WriteLine("A válasz: "+answer);
    return Results.Ok(new { answer });
    }catch(Exception e)
    {
        return Results.Json(new { error = e.Message }, statusCode: 500);
    }

});
app.Run();*/

app.UseCors("frontend");

app.UseAuthentication();
app.UseAuthorization();

app.MapControllers();

app.Run();





