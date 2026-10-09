using System;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using ef;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

public class MetricsAnalysisWorker : BackgroundService
{
    private readonly MetricsAnalysisQueue queue;
    private readonly IServiceScopeFactory scopeFactory;
    private readonly ILogger<MetricsAnalysisWorker> logger;

    public MetricsAnalysisWorker(MetricsAnalysisQueue analysisQueue, IServiceScopeFactory scopes, ILogger<MetricsAnalysisWorker> log)
    {
        queue = analysisQueue;
        scopeFactory = scopes;
        logger = log;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        await ReleaseInterruptedAsync(stoppingToken);

        await foreach (var analysisId in queue.ReadAllAsync(stoppingToken))
        {
            using var scope = scopeFactory.CreateScope();
            var analysis = scope.ServiceProvider.GetRequiredService<MetricsAnalysisService>();

            try
            {
                await analysis.RunAsync(analysisId, stoppingToken);
            }
            catch (Exception ex)
            {
                logger.LogError(ex, "Metrics analysis worker failed for {AnalysisId}", analysisId);
            }
        }
    }

    private async Task ReleaseInterruptedAsync(CancellationToken cancellationToken)
    {
        try
        {
            using var scope = scopeFactory.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<CodeDbContext>();

            var stuck = await db.MetricsAnalyses
                .Where(a => MetricsAnalysisStatus.InFlight.Contains(a.Status))
                .ToListAsync(cancellationToken);

            if (stuck.Count == 0) return;

            foreach (var analysis in stuck)
            {
                analysis.Status = MetricsAnalysisStatus.Failed;
                analysis.ErrorMessage = "Interrupted by a backend restart. Please run the analysis again.";
            }

            await db.SaveChangesAsync(cancellationToken);
            logger.LogWarning("Released {Count} metrics analyses left over from a restart", stuck.Count);
        }
        catch (Exception ex)
        {
            logger.LogError(ex, "Could not release interrupted metrics analyses");
        }
    }
}
