(function () {
    var operatorField = document.getElementById("id_operator");
    if (!operatorField) {
        return;
    }

    operatorField.addEventListener("change", function () {
        var operatorId = operatorField.value;
        var url = new URL(window.location.href);

        if (operatorId) {
            url.searchParams.set("operator", operatorId);
        } else {
            url.searchParams.delete("operator");
        }

        window.location.assign(url.toString());
    });
})();
