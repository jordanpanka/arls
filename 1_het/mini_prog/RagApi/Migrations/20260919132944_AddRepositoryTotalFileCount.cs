using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace RagApi.Migrations
{
    /// <inheritdoc />
    public partial class AddRepositoryTotalFileCount : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<int>(
                name: "TotalFileCount",
                table: "Repository",
                type: "int",
                nullable: false,
                defaultValue: 0);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropColumn(
                name: "TotalFileCount",
                table: "Repository");
        }
    }
}
