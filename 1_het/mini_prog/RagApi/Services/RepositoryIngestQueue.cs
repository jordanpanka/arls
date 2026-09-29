using System.Collections.Generic;
using System.Threading;
using System.Threading.Channels;
using System.Threading.Tasks;

/// <summary>
/// Hands repository ids from the request thread to the background worker.
/// Only the id travels: the worker reloads the record in its own scope, so
/// nothing is shared across the DbContext boundary.
/// </summary>
public class RepositoryIngestQueue
{
    private readonly Channel<int> channel = Channel.CreateUnbounded<int>();

    public ValueTask EnqueueAsync(int repositoryId) => channel.Writer.WriteAsync(repositoryId);

    public IAsyncEnumerable<int> ReadAllAsync(CancellationToken cancellationToken) =>
        channel.Reader.ReadAllAsync(cancellationToken);
}
