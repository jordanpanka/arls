using System.Collections.Generic;
using System.Threading;
using System.Threading.Channels;
using System.Threading.Tasks;

public class MetricsAnalysisQueue
{
    private readonly Channel<int> channel = Channel.CreateUnbounded<int>();

    public ValueTask EnqueueAsync(int analysisId) => channel.Writer.WriteAsync(analysisId);

    public IAsyncEnumerable<int> ReadAllAsync(CancellationToken cancellationToken) =>
        channel.Reader.ReadAllAsync(cancellationToken);
}
