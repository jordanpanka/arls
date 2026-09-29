using DocumentFormat.OpenXml.Office2016.Excel;
using Microsoft.EntityFrameworkCore;
namespace ef;

public class CodeDbContext : DbContext
{
    public CodeDbContext(DbContextOptions<CodeDbContext> options)
        : base(options)
    {
    }
    public DbSet<DbUser> Users { get; set; }
    public DbSet<DbProject> Projects { get; set; }
    public DbSet<DbInvestigation> Investigations { get; set; }
    public DbSet<DbFile> Files { get; set; }
    public DbSet<DbRepository> Repositories { get; set; }
    public DbSet<DbConversation> Conversations {get; set;}

    public DbSet<DbMessage> Messages {get; set;}
    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        base.OnModelCreating(modelBuilder);

        modelBuilder.Entity<DbInvestigation>()
            .HasOne(u=>u.User)
            .WithMany(p=>p.Investigations)
            .HasForeignKey(f=>f.UserID)
            .OnDelete(DeleteBehavior.Cascade);

        modelBuilder.Entity<DbProject>()
            .HasOne(i=>i.Investigation)
            .WithMany(p=>p.Projects)
            .HasForeignKey(f=>f.InvestigationID)
            .OnDelete(DeleteBehavior.Cascade);

        modelBuilder.Entity<DbFile>()
            .HasOne(p=>p.Project)
            .WithMany(f=>f.Files)
            .HasForeignKey(f=>f.ProjectID)
            .OnDelete(DeleteBehavior.Cascade);

        modelBuilder.Entity<DbRepository>()
            .HasOne(r=>r.Project)
            .WithMany(p=>p.Repositories)
            .HasForeignKey(r=>r.ProjectID)
            .OnDelete(DeleteBehavior.Cascade);

        modelBuilder.Entity<DbConversation>()
            .HasOne(p=>p.Project)
            .WithMany(c=>c.Conversations)
            .HasForeignKey(c=>c.ProjectID)
            .OnDelete(DeleteBehavior.Cascade);

        modelBuilder.Entity<DbMessage>()
            .HasOne(c=>c.Conversation)
            .WithMany(m=>m.Messages)
            .HasForeignKey(m=>m.ConversationID)
            .OnDelete(DeleteBehavior.Cascade);
    }
}