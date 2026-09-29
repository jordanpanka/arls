using ef;
using Microsoft.EntityFrameworkCore;

public class FileServiceTests
{
    private CodeDbContext CreateDb()
    {
        var options = new DbContextOptionsBuilder<CodeDbContext>()
            .UseInMemoryDatabase(Guid.NewGuid().ToString())
            .Options;

        return new CodeDbContext(options);
    }


}