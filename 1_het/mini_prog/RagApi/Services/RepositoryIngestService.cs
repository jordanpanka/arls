using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using ef;
using Microsoft.AspNetCore.Http;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;

public class RepositoryIngestService
{
    private readonly CodeDbContext db;
    private readonly GitHubService gitHub;
    private readonly FileService fileService;
    private readonly MinioService minioService;
    private readonly RepositoryIngestQueue queue;
    private readonly ILogger<RepositoryIngestService> logger;

   
    private const int BatchSize = 5;

    public RepositoryIngestService(
        CodeDbContext codeDbContext,
        GitHubService gitHubService,
        FileService files,
        MinioService minio,
        RepositoryIngestQueue ingestQueue,
        ILogger<RepositoryIngestService> log)
    {
        db = codeDbContext;
        gitHub = gitHubService;
        fileService = files;
        minioService = minio;
        queue = ingestQueue;
        logger = log;
    }

   
    public async Task<ServiceResult> QueueAsync(
        int userId, int invId, int projectId,
        string owner, string repo, string reference)
    {
        var project = await db.Projects
            .FirstOrDefaultAsync(p => p.ID == projectId && p.InvestigationID == invId);

        if (project == null) return ServiceResult.Fail("Project doesn't exist.");

        var ownsIt = await db.Investigations
            .AnyAsync(i => i.ID == invId && i.UserID == userId);

        if (!ownsIt) return ServiceResult.Fail("Investigation doesn't belong to this user.");

        
        var busy = await db.Repositories
            .AnyAsync(r => r.ProjectID == projectId && RepositoryStatus.InFlight.Contains(r.Status));

        if (busy) return ServiceResult.Fail("An import is already running for this project.");

       
        var quota = await gitHub.GetRateLimitAsync();

        if (quota.Ok)
        {
            var limit = (RateLimitState)quota.Data!;

            if (limit.Remaining < GitHubService.RequestsPerImport)
                return ServiceResult.Fail(
                    $"GitHub rate limit exhausted ({limit.Limit} requests/hour). " +
                    $"It resets at {limit.ResetUtc:HH:mm} UTC.");
        }

        var record = new DbRepository
        {
            ProjectID = projectId,
            Owner = owner,
            Name = repo,
            Reference = reference,
            Status = RepositoryStatus.Queued
        };

        db.Repositories.Add(record);
        await db.SaveChangesAsync();

        await queue.EnqueueAsync(record.ID);

        return ServiceResult.Success(new
        {
            repositoryId = record.ID,
            status = record.Status
        });
    }

    
    public async Task RunAsync(int repositoryId, CancellationToken cancellationToken = default)
    {
        var record = await db.Repositories.FirstOrDefaultAsync(r => r.ID == repositoryId, cancellationToken);
        if (record == null)
        {
            logger.LogWarning("Repository {RepositoryId} disappeared before it could be ingested", repositoryId);
            return;
        }

    
        var context = await db.Projects
            .Where(p => p.ID == record.ProjectID)
            .Select(p => new { InvId = p.InvestigationID, UserId = p.Investigation.UserID })
            .FirstOrDefaultAsync(cancellationToken);

        if (context == null)
        {
            await MarkFailedAsync(record, "Project disappeared before the import started.");
            return;
        }

        RepositorySnapshot? snapshot = null;

        try
        {
            record.Status = RepositoryStatus.Fetching;
            await db.SaveChangesAsync(cancellationToken);

            var fetch = await gitHub.FetchSnapshotAsync(
                record.Owner, record.Name, record.Reference, cancellationToken);

            if (!fetch.Ok)
            {
                await MarkFailedAsync(record, fetch.Error!);
                return;
            }

            snapshot = (RepositorySnapshot)fetch.Data!;

            record.CommitSha = snapshot.CommitSha;
            record.SkippedFileCount = snapshot.SkippedCount;
            record.Status = RepositoryStatus.Indexing;
            await db.SaveChangesAsync(cancellationToken);

            logger.LogInformation(
                "Repository {Owner}/{Repo}@{Sha}: {Kept} files to index, {Skipped} skipped of {Total} entries",
                record.Owner, record.Name, snapshot.CommitSha, snapshot.Entries.Count,
                snapshot.SkippedCount, snapshot.TotalEntries);

            if (snapshot.Entries.Count == 0)
            {
                await MarkFailedAsync(record, "No indexable files found in the repository.");
                return;
            }

           
            var stored = await fileService.GetStoredFileKeysAsync(
                context.UserId, context.InvId, record.ProjectID);

            var pending = snapshot.Entries
                .Where(e => !stored.Contains(FileService.StoredFileKey(e.Path, Path.GetFileName(e.Path))))
                .ToList();

            record.SkippedFileCount += snapshot.Entries.Count - pending.Count;

            if (pending.Count == 0)
            {
                await MarkFailedAsync(record, "Every file in this repository was already uploaded.");
                return;
            }

            record.TotalFileCount = pending.Count;
            await db.SaveChangesAsync(cancellationToken);

           
            for (var offset = 0; offset < pending.Count; offset += BatchSize)
            {
                cancellationToken.ThrowIfCancellationRequested();

                var batch = pending.Skip(offset).Take(BatchSize).Select(snapshot.Open).ToList();

                try
                {
                    var files = batch.Select(b => b.File).ToList();
                    var paths = batch.Select(b => b.RelativePath).ToList();

                    var indexed = await fileService.UploadQdrantPythonAsync(
                        context.UserId, files, paths, record.ProjectID, context.InvId);

                    if (!indexed.Ok)
                    {
                        await MarkFailedAsync(record, indexed.Error!);
                        return;
                    }

                    var recorded = await fileService.UploadAsync(record.ProjectID, files, paths);
                    if (!recorded.Ok)
                    {
                        await MarkFailedAsync(record, "Failed to record repository files.");
                        return;
                    }

                    await minioService.UploadAsync(context.UserId, files, paths, record.ProjectID, context.InvId);

                    record.IndexedFileCount += files.Count;
                    await db.SaveChangesAsync(cancellationToken);
                }
                finally
                {
                    foreach (var file in batch) file.Dispose();
                }

                logger.LogInformation(
                    "Repository {RepositoryId}: {Done}/{Total} files indexed",
                    record.ID, record.IndexedFileCount, record.TotalFileCount);
            }

            record.Status = RepositoryStatus.Ready;
            record.IndexedAt = DateTime.UtcNow;
            await db.SaveChangesAsync(cancellationToken);
        }
        catch (OperationCanceledException)
        {
            await MarkFailedAsync(record, "Import stopped because the backend is shutting down.");
        }
        catch (Exception ex)
        {
            logger.LogError(ex, "Repository ingest failed for {Owner}/{Repo}", record.Owner, record.Name);
            await MarkFailedAsync(record, ex.Message);
        }
        finally
        {
            snapshot?.Dispose();
        }
    }

    private async Task MarkFailedAsync(DbRepository record, string error)
    {
        record.Status = RepositoryStatus.Failed;
        record.ErrorMessage = error.Length > 1000 ? error[..1000] : error;

        // Deliberately not passing the cancellation token: a shutdown is exactly
        // when this write matters most.
        await db.SaveChangesAsync();
    }

    public async Task<ServiceResult> GetForProjectAsync(int projectId)
    {
        var repositories = await db.Repositories
            .Where(r => r.ProjectID == projectId)
            .OrderByDescending(r => r.CreatedAt)
            .Select(r => new
            {
                id = r.ID,
                owner = r.Owner,
                name = r.Name,
                reference = r.Reference,
                commitSha = r.CommitSha,
                status = r.Status,
                error = r.ErrorMessage,
                indexed = r.IndexedFileCount,
                total = r.TotalFileCount,
                skipped = r.SkippedFileCount,
                indexedAt = r.IndexedAt
            })
            .ToListAsync();

        return ServiceResult.Success(repositories);
    }
}
