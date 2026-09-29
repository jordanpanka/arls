using Minio;
using Minio.DataModel.Args;

public class MinioService
{
    private readonly IMinioClient _minio;
    private readonly string _bucket;

    public MinioService(IMinioClient minio, IConfiguration configuration)
    {
        _minio = minio;
        _bucket = configuration["Minio:Bucket"] ?? "ragappdata";
    }

    // PutObjectAsync fails if the bucket is missing, and nothing else creates it.
    // Cheap enough to check per upload batch, and keeps local runs working too.
    private async Task EnsureBucketAsync()
    {
        var exists = await _minio.BucketExistsAsync(
            new BucketExistsArgs().WithBucket(_bucket)
        );

        if (!exists)
        {
            await _minio.MakeBucketAsync(
                new MakeBucketArgs().WithBucket(_bucket)
            );
        }
    }

    public async Task UploadAsync(int userId, List<IFormFile> files, List<string> paths, int projectId, int invId)
    {
        await EnsureBucketAsync();

        for (int i = 0; i < files.Count; i++)
        {
            var f = files[i];
            var path = paths[i];

            var objectName =
                $"users/{userId}/investigations/{invId}/projects/{projectId}/original/{path}";

            using var stream = f.OpenReadStream();

            await _minio.PutObjectAsync(
                new PutObjectArgs()
                    .WithBucket(_bucket)
                    .WithObject(objectName)
                    .WithStreamData(stream)
                    .WithObjectSize(f.Length)
                    .WithContentType(f.ContentType)
            );
        }
    }
}
