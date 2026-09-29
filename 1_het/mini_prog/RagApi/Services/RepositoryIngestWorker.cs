using System;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using ef;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;


public class RepositoryIngestWorker : BackgroundService
{
    private readonly RepositoryIngestQueue queue;
    private readonly IServiceScopeFactory scopeFactory;
    private readonly ILogger<RepositoryIngestWorker> logger;

    public RepositoryIngestWorker(
        RepositoryIngestQueue ingestQueue,
        IServiceScopeFactory scopes,
        ILogger<RepositoryIngestWorker> log)
    {
        queue = ingestQueue;
        scopeFactory = scopes;
        logger = log;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        await ReleaseInterruptedAsync(stoppingToken);

        await foreach (var repositoryId in queue.ReadAllAsync(stoppingToken))
        {
            using var scope = scopeFactory.CreateScope();
            var ingest = scope.ServiceProvider.GetRequiredService<RepositoryIngestService>();

            try
            {
                await ingest.RunAsync(repositoryId, stoppingToken);
            }
            catch (Exception ex)
            {
                // RunAsync records its own failures; this only catches the case
                // where it could not even get that far, so the worker survives.
                logger.LogError(ex, "Repository ingest worker failed for {RepositoryId}", repositoryId);
            }
        }
    }

   
    private async Task ReleaseInterruptedAsync(CancellationToken cancellationToken)
    {
        try
        {
            using var scope = scopeFactory.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<CodeDbContext>();

            var stuck = await db.Repositories
                .Where(r => RepositoryStatus.InFlight.Contains(r.Status))
                .ToListAsync(cancellationToken);

            if (stuck.Count == 0) return;

            foreach (var record in stuck)
            {
                record.Status = RepositoryStatus.Failed;
                record.ErrorMessage = "Interrupted by a backend restart. Please try again.";
            }

            await db.SaveChangesAsync(cancellationToken);
            logger.LogWarning("Released {Count} repository ingest(s) left over from a restart", stuck.Count);
        }
        catch (Exception ex)
        {
            logger.LogError(ex, "Could not release interrupted repository ingests");
        }
    }
}
