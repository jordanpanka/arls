using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace RagApi.Migrations
{
    /// <inheritdoc />
    public partial class AddProjectInvestigationRelations : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropForeignKey(
                name: "FK_Project_Investigation_DbInvestigationID",
                table: "Project");

            migrationBuilder.DropIndex(
                name: "IX_Project_DbInvestigationID",
                table: "Project");

            migrationBuilder.DropColumn(
                name: "DbInvestigationID",
                table: "Project");

            migrationBuilder.CreateIndex(
                name: "IX_Project_InvestigationID",
                table: "Project",
                column: "InvestigationID");

            migrationBuilder.AddForeignKey(
                name: "FK_Project_Investigation_InvestigationID",
                table: "Project",
                column: "InvestigationID",
                principalTable: "Investigation",
                principalColumn: "ID",
                onDelete: ReferentialAction.Cascade);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropForeignKey(
                name: "FK_Project_Investigation_InvestigationID",
                table: "Project");

            migrationBuilder.DropIndex(
                name: "IX_Project_InvestigationID",
                table: "Project");

            migrationBuilder.AddColumn<int>(
                name: "DbInvestigationID",
                table: "Project",
                type: "int",
                nullable: true);

            migrationBuilder.CreateIndex(
                name: "IX_Project_DbInvestigationID",
                table: "Project",
                column: "DbInvestigationID");

            migrationBuilder.AddForeignKey(
                name: "FK_Project_Investigation_DbInvestigationID",
                table: "Project",
                column: "DbInvestigationID",
                principalTable: "Investigation",
                principalColumn: "ID");
        }
    }
}
