using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace RagApi.Migrations
{
    /// <inheritdoc />
    public partial class AddedInvestigationChanges : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<int>(
                name: "DbInvestigationID",
                table: "Project",
                type: "int",
                nullable: true);

            migrationBuilder.AddColumn<int>(
                name: "InvestigationID",
                table: "Project",
                type: "int",
                nullable: false,
                defaultValue: 0);

            migrationBuilder.CreateTable(
                name: "File",
                columns: table => new
                {
                    ID = table.Column<int>(type: "int", nullable: false)
                        .Annotation("SqlServer:Identity", "1, 1"),
                    ProjectID = table.Column<int>(type: "int", nullable: false),
                    Name = table.Column<string>(type: "nvarchar(max)", nullable: false),
                    path = table.Column<string>(type: "nvarchar(max)", nullable: false),
                    DbProjectID = table.Column<int>(type: "int", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_File", x => x.ID);
                    table.ForeignKey(
                        name: "FK_File_Project_DbProjectID",
                        column: x => x.DbProjectID,
                        principalTable: "Project",
                        principalColumn: "ID");
                });

            migrationBuilder.CreateTable(
                name: "Investigation",
                columns: table => new
                {
                    ID = table.Column<int>(type: "int", nullable: false)
                        .Annotation("SqlServer:Identity", "1, 1"),
                    UserID = table.Column<int>(type: "int", nullable: false),
                    Name = table.Column<string>(type: "nvarchar(max)", nullable: false),
                    Description = table.Column<string>(type: "nvarchar(max)", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_Investigation", x => x.ID);
                    table.ForeignKey(
                        name: "FK_Investigation_User_UserID",
                        column: x => x.UserID,
                        principalTable: "User",
                        principalColumn: "ID",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateIndex(
                name: "IX_Project_DbInvestigationID",
                table: "Project",
                column: "DbInvestigationID");

            migrationBuilder.CreateIndex(
                name: "IX_File_DbProjectID",
                table: "File",
                column: "DbProjectID");

            migrationBuilder.CreateIndex(
                name: "IX_Investigation_UserID",
                table: "Investigation",
                column: "UserID");

            migrationBuilder.AddForeignKey(
                name: "FK_Project_Investigation_DbInvestigationID",
                table: "Project",
                column: "DbInvestigationID",
                principalTable: "Investigation",
                principalColumn: "ID");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropForeignKey(
                name: "FK_Project_Investigation_DbInvestigationID",
                table: "Project");

            migrationBuilder.DropTable(
                name: "File");

            migrationBuilder.DropTable(
                name: "Investigation");

            migrationBuilder.DropIndex(
                name: "IX_Project_DbInvestigationID",
                table: "Project");

            migrationBuilder.DropColumn(
                name: "DbInvestigationID",
                table: "Project");

            migrationBuilder.DropColumn(
                name: "InvestigationID",
                table: "Project");
        }
    }
}
