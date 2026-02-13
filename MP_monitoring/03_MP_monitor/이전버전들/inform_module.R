# panel3_tab.R 내의 panel3UI 함수
addResourcePath("external", "./www")

panel3UI <- function(id) {
  ns <- NS(id)
  tagList(
    # Markdown 또는 HTML 파일을 포함하는 UI 출력
    htmlOutput(ns("inc"))
    
  )
}
# 
# panel3_tab.R 내의 panel3Server 함수
# panel3Server <- function(id) {
#   moduleServer(id, function(input, output, session) {
# 
#     getPage<-function() {
#       return(includeHTML(path = "www/test_v2.html"))
#     }
#     output$inc<-renderUI({getPage()})
# 
#   })
# }
# 
# panel3_tab.R 내의 panel3Server 함수
panel3Server <- function(id) {
  moduleServer(id, function(input, output, session) {
    ns <- NS(id)

    output$inc <- renderUI({
      tags$iframe(src = "external/inform_20250422.html", style = "height: calc(100vh - 50px);width: calc(100% + 60px);margin: 0 -30px;", frameBorder = "0")
    })
  })
}
